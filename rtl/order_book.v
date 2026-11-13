module order_book #(
    parameter SET_BITS   = 10,
    parameter LEVEL_BITS = 12
) (
    input  wire        clk,
    input  wire        rst,
    input  wire [15:0] target_locate,
    input  wire [31:0] base_price,

    input  wire        msg_valid,
    input  wire [7:0]  msg_type,
    input  wire [15:0] stock_locate,
    input  wire [63:0] order_ref,
    input  wire [63:0] new_order_ref,
    input  wire        side,
    input  wire [31:0] shares,
    input  wire [31:0] price,

    output wire        busy,
    output reg         book_update,
    output reg         bid_valid,
    output wire [31:0] bid_price,
    output reg  [31:0] bid_qty,
    output reg         ask_valid,
    output wire [31:0] ask_price,
    output reg  [31:0] ask_qty,
    output reg  [15:0] collisions,
    output reg  [15:0] out_of_range
);

    localparam WAYS     = 4;
    localparam LEVELS   = 1 << LEVEL_BITS;
    localparam ENTRY_W  = 1 + 64 + 1 + LEVEL_BITS + 32;
    localparam SET_W    = WAYS * ENTRY_W;
    localparam LVL_ADDR = LEVEL_BITS + 1;
    localparam TICK     = 100;
    localparam CLR_BITS = (SET_BITS > LVL_ADDR) ? SET_BITS : LVL_ADDR;

    localparam [2:0] S_CLEAR   = 3'd0;
    localparam [2:0] S_IDLE    = 3'd1;
    localparam [2:0] S_ADD     = 3'd2;
    localparam [2:0] S_FIND    = 3'd3;
    localparam [2:0] S_LEVEL   = 3'd4;
    localparam [2:0] S_SCAN    = 3'd5;
    localparam [2:0] S_REPLACE = 3'd6;

    localparam [1:0] K_ADD     = 2'd0;
    localparam [1:0] K_REDUCE  = 2'd1;
    localparam [1:0] K_DELETE  = 2'd2;
    localparam [1:0] K_REPLACE = 2'd3;

    reg [2:0]            state;
    reg [CLR_BITS-1:0]   clr_idx;

    reg [1:0]            kind;
    reg [63:0]           m_ref;
    reg [63:0]           m_new_ref;
    reg [31:0]           m_shares;
    reg [LEVEL_BITS-1:0] m_lvl;
    reg                  m_in_window;

    reg [63:0]           a_ref;
    reg                  a_side;

    reg                  r_side;
    reg [LEVEL_BITS-1:0] r_lvl;
    reg [31:0]           r_dec;

    reg [LEVEL_BITS-1:0] scan_idx;
    reg [LEVEL_BITS-1:0] bid_idx;
    reg [LEVEL_BITS-1:0] ask_idx;

    reg                  ord_we;
    reg  [SET_BITS-1:0]  ord_waddr;
    reg  [SET_W-1:0]     ord_wdata;
    reg                  ord_re;
    reg  [SET_BITS-1:0]  ord_raddr;
    wire [SET_W-1:0]     set_q;

    reg                  lvl_we;
    reg  [LVL_ADDR-1:0]  lvl_waddr;
    reg  [31:0]          lvl_wdata;
    reg                  lvl_re;
    reg  [LVL_ADDR-1:0]  lvl_raddr;
    wire [31:0]          lvl_q;

    ram_sdp #(.WIDTH(SET_W), .ADDR(SET_BITS)) orders (
        .clk   (clk),
        .we    (ord_we),
        .waddr (ord_waddr),
        .wdata (ord_wdata),
        .re    (ord_re),
        .raddr (ord_raddr),
        .rdata (set_q)
    );

    ram_sdp #(.WIDTH(32), .ADDR(LVL_ADDR)) levels (
        .clk   (clk),
        .we    (lvl_we),
        .waddr (lvl_waddr),
        .wdata (lvl_wdata),
        .re    (lvl_re),
        .raddr (lvl_raddr),
        .rdata (lvl_q)
    );

    function [SET_BITS-1:0] set_of(input [63:0] id);
        set_of = id[SET_BITS-1:0] ^ id[2*SET_BITS-1:SET_BITS];
    endfunction

    wire is_add     = (msg_type == "A") || (msg_type == "F");
    wire is_reduce  = (msg_type == "E") || (msg_type == "C") || (msg_type == "X");
    wire is_delete  = (msg_type == "D");
    wire is_replace = (msg_type == "U");
    wire for_us     = msg_valid && (stock_locate == target_locate) &&
                      (is_add || is_reduce || is_delete || is_replace);

    wire [31:0] offset    = price - base_price;
    wire [31:0] tick      = offset / TICK;
    wire        in_window = (price >= base_price) && (tick < LEVELS);

    reg [WAYS-1:0] hit;
    reg [WAYS-1:0] empty;
    reg [1:0]      hit_way;
    reg [1:0]      free_way;

    integer w;
    always @(*) begin
        hit_way  = 2'd0;
        free_way = 2'd0;
        for (w = WAYS - 1; w >= 0; w = w - 1) begin
            hit[w]   = set_q[w*ENTRY_W + ENTRY_W - 1] && (set_q[w*ENTRY_W + ENTRY_W - 2 -: 64] == m_ref);
            empty[w] = !set_q[w*ENTRY_W + ENTRY_W - 1];
            if (hit[w])   hit_way  = w[1:0];
            if (empty[w]) free_way = w[1:0];
        end
    end

    wire                  found     = |hit;
    wire                  full      = ~|empty;
    wire [ENTRY_W-1:0]    hit_entry = set_q[hit_way*ENTRY_W +: ENTRY_W];
    wire                  e_side    = hit_entry[LEVEL_BITS + 32];
    wire [LEVEL_BITS-1:0] e_lvl     = hit_entry[32 +: LEVEL_BITS];
    wire [31:0]           e_shares  = hit_entry[31:0];
    wire [31:0]           dec       = (kind == K_REDUCE && m_shares < e_shares) ? m_shares : e_shares;
    wire [31:0]           left      = e_shares - dec;
    wire [31:0]           lvl_plus  = lvl_q + m_shares;
    wire [31:0]           lvl_minus = lvl_q - r_dec;

    reg [SET_W-1:0] set_add;
    reg [SET_W-1:0] set_upd;

    always @(*) begin
        set_add = set_q;
        set_add[free_way*ENTRY_W +: ENTRY_W] = {1'b1, a_ref, a_side, m_lvl, m_shares};

        set_upd = set_q;
        set_upd[hit_way*ENTRY_W +: ENTRY_W] = (left == 32'd0) ? {ENTRY_W{1'b0}}
                                                             : {1'b1, m_ref, e_side, e_lvl, left};
    end

    wire add_ok = (m_shares != 32'd0) && m_in_window && !full;

    wire [LEVEL_BITS-1:0] best_idx   = r_side ? bid_idx : ask_idx;
    wire                  at_best    = (r_lvl == best_idx);
    wire                  emptied    = (lvl_minus == 32'd0);
    wire                  r_last     = r_side ? (r_lvl == {LEVEL_BITS{1'b0}}) : (&r_lvl);
    wire [LEVEL_BITS-1:0] r_next     = r_side ? r_lvl - 1'b1 : r_lvl + 1'b1;
    wire                  start_scan = at_best && emptied && !r_last;

    wire                  scan_hit   = (lvl_q != 32'd0);
    wire                  scan_last  = r_side ? (scan_idx == {LEVEL_BITS{1'b0}}) : (&scan_idx);
    wire [LEVEL_BITS-1:0] scan_next  = r_side ? scan_idx - 1'b1 : scan_idx + 1'b1;

    always @(*) begin
        ord_we    = 1'b0;
        ord_waddr = set_of(m_ref);
        ord_wdata = set_upd;
        ord_re    = 1'b0;
        ord_raddr = set_of(order_ref);

        lvl_we    = 1'b0;
        lvl_waddr = {r_side, r_lvl};
        lvl_wdata = lvl_minus;
        lvl_re    = 1'b0;
        lvl_raddr = {side, tick[LEVEL_BITS-1:0]};

        case (state)
            S_CLEAR: begin
                ord_we    = 1'b1;
                ord_waddr = clr_idx[SET_BITS-1:0];
                ord_wdata = {SET_W{1'b0}};
                lvl_we    = 1'b1;
                lvl_waddr = clr_idx[LVL_ADDR-1:0];
                lvl_wdata = 32'd0;
            end

            S_IDLE: begin
                ord_re = for_us;
                lvl_re = for_us && is_add;
            end

            S_ADD: begin
                ord_we    = add_ok;
                ord_waddr = set_of(a_ref);
                ord_wdata = set_add;
                lvl_we    = add_ok;
                lvl_waddr = {a_side, m_lvl};
                lvl_wdata = lvl_plus;
            end

            S_FIND: begin
                ord_we    = found;
                lvl_re    = found;
                lvl_raddr = {e_side, e_lvl};
            end

            S_LEVEL: begin
                lvl_we    = 1'b1;
                lvl_re    = start_scan;
                lvl_raddr = {r_side, r_next};
            end

            S_SCAN: begin
                lvl_re    = !scan_hit && !scan_last;
                lvl_raddr = {r_side, scan_next};
            end

            S_REPLACE: begin
                ord_re    = 1'b1;
                ord_raddr = set_of(a_ref);
                lvl_re    = 1'b1;
                lvl_raddr = {a_side, m_lvl};
            end

            default: ;
        endcase
    end

    assign busy      = (state != S_IDLE);
    assign bid_price = base_price + bid_idx * TICK;
    assign ask_price = base_price + ask_idx * TICK;

    task finish_reduce;
        begin
            if (kind == K_REPLACE) begin
                state <= S_REPLACE;
            end else begin
                book_update <= 1'b1;
                state       <= S_IDLE;
            end
        end
    endtask

    always @(posedge clk) begin
        book_update <= 1'b0;

        if (rst) begin
            state        <= S_CLEAR;
            clr_idx      <= {CLR_BITS{1'b0}};
            bid_valid    <= 1'b0;
            ask_valid    <= 1'b0;
            bid_idx      <= {LEVEL_BITS{1'b0}};
            ask_idx      <= {LEVEL_BITS{1'b0}};
            bid_qty      <= 32'd0;
            ask_qty      <= 32'd0;
            collisions   <= 16'd0;
            out_of_range <= 16'd0;
        end else begin
            case (state)
                S_CLEAR: begin
                    clr_idx <= clr_idx + 1'b1;
                    if (&clr_idx)
                        state <= S_IDLE;
                end

                S_IDLE: begin
                    if (for_us) begin
                        m_ref       <= order_ref;
                        m_new_ref   <= new_order_ref;
                        m_shares    <= shares;
                        m_lvl       <= tick[LEVEL_BITS-1:0];
                        m_in_window <= in_window;
                        if (is_add) begin
                            kind   <= K_ADD;
                            a_ref  <= order_ref;
                            a_side <= side;
                            state  <= S_ADD;
                        end else begin
                            kind  <= is_reduce ? K_REDUCE : is_delete ? K_DELETE : K_REPLACE;
                            state <= S_FIND;
                        end
                    end
                end

                S_ADD: begin
                    if (m_shares == 32'd0) begin
                    end else if (!m_in_window) begin
                        out_of_range <= out_of_range + 1'b1;
                    end else if (full) begin
                        collisions <= collisions + 1'b1;
                    end else if (a_side) begin
                        if (!bid_valid || m_lvl > bid_idx) begin
                            bid_valid <= 1'b1;
                            bid_idx   <= m_lvl;
                            bid_qty   <= lvl_plus;
                        end else if (m_lvl == bid_idx) begin
                            bid_qty <= lvl_plus;
                        end
                    end else begin
                        if (!ask_valid || m_lvl < ask_idx) begin
                            ask_valid <= 1'b1;
                            ask_idx   <= m_lvl;
                            ask_qty   <= lvl_plus;
                        end else if (m_lvl == ask_idx) begin
                            ask_qty <= lvl_plus;
                        end
                    end
                    book_update <= 1'b1;
                    state       <= S_IDLE;
                end

                S_FIND: begin
                    if (!found) begin
                        book_update <= 1'b1;
                        state       <= S_IDLE;
                    end else begin
                        r_side <= e_side;
                        r_lvl  <= e_lvl;
                        r_dec  <= dec;
                        a_side <= e_side;
                        a_ref  <= m_new_ref;
                        state  <= S_LEVEL;
                    end
                end

                S_LEVEL: begin
                    if (start_scan) begin
                        scan_idx <= r_next;
                        state    <= S_SCAN;
                    end else begin
                        if (at_best && emptied) begin
                            if (r_side) bid_valid <= 1'b0;
                            else        ask_valid <= 1'b0;
                        end else if (at_best) begin
                            if (r_side) bid_qty <= lvl_minus;
                            else        ask_qty <= lvl_minus;
                        end
                        finish_reduce;
                    end
                end

                S_SCAN: begin
                    if (scan_hit) begin
                        if (r_side) begin
                            bid_idx <= scan_idx;
                            bid_qty <= lvl_q;
                        end else begin
                            ask_idx <= scan_idx;
                            ask_qty <= lvl_q;
                        end
                        finish_reduce;
                    end else if (scan_last) begin
                        if (r_side) bid_valid <= 1'b0;
                        else        ask_valid <= 1'b0;
                        finish_reduce;
                    end else begin
                        scan_idx <= scan_next;
                    end
                end

                S_REPLACE: begin
                    state <= S_ADD;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
