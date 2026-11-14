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
    output reg  [31:0] bid_price,
    output reg  [31:0] bid_qty,
    output reg         ask_valid,
    output reg  [31:0] ask_price,
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
    localparam WINDOW   = LEVELS * TICK;
    localparam CLR_BITS = (SET_BITS > LVL_ADDR) ? SET_BITS : LVL_ADDR;

    localparam [3:0] S_CLEAR    = 4'd0;
    localparam [3:0] S_IDLE     = 4'd1;
    localparam [3:0] S_DIV      = 4'd2;
    localparam [3:0] S_PREP     = 4'd3;
    localparam [3:0] S_REPLACE  = 4'd4;
    localparam [3:0] S_ADD      = 4'd5;
    localparam [3:0] S_ADD_WB   = 4'd6;
    localparam [3:0] S_FIND     = 4'd7;
    localparam [3:0] S_REDUCE   = 4'd8;
    localparam [3:0] S_LEVEL    = 4'd9;
    localparam [3:0] S_LEVEL_WB = 4'd10;
    localparam [3:0] S_SCAN     = 4'd11;

    localparam [1:0] K_ADD     = 2'd0;
    localparam [1:0] K_REDUCE  = 2'd1;
    localparam [1:0] K_DELETE  = 2'd2;
    localparam [1:0] K_REPLACE = 2'd3;

    reg [3:0]            state;
    reg [CLR_BITS-1:0]   clr_idx;

    reg [1:0]            kind;
    reg [63:0]           m_ref;
    reg [63:0]           m_new_ref;
    reg [SET_BITS-1:0]   m_set;
    reg [31:0]           m_shares;
    reg [LEVEL_BITS-1:0] m_lvl;
    reg                  m_in_window;
    reg [31:0]           m_lvl_price;

    reg [31:0]           p_diff;
    reg                  p_ge_base;
    reg [34:0]           p_prod;
    reg                  p_win;

    reg [SET_W-1:0]      set_r;

    reg [63:0]           a_ref;
    reg [SET_BITS-1:0]   a_set;
    reg                  a_side;
    reg [1:0]            a_free;
    reg                  a_full;
    reg                  a_nonzero;
    reg [31:0]           a_new_lvl;

    reg                  f_found;
    reg [1:0]            f_way;
    reg                  f_side;
    reg [LEVEL_BITS-1:0] f_lvl;
    reg [31:0]           f_shares;

    reg                  r_side;
    reg [LEVEL_BITS-1:0] r_lvl;
    reg [31:0]           r_dec;
    reg [ENTRY_W-1:0]    r_entry;
    reg [31:0]           r_new_lvl;
    reg                  r_emptied;

    reg [LEVEL_BITS-1:0] scan_idx;
    reg [31:0]           scan_price;
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

    function [SET_BITS-1:0] set_of(input [2*SET_BITS-1:0] id);
        set_of = id[SET_BITS-1:0] ^ id[2*SET_BITS-1:SET_BITS];
    endfunction

    wire is_add     = (msg_type == "A") || (msg_type == "F");
    wire is_reduce  = (msg_type == "E") || (msg_type == "C") || (msg_type == "X");
    wire is_delete  = (msg_type == "D");
    wire is_replace = (msg_type == "U");
    wire for_us     = msg_valid && (stock_locate == target_locate) &&
                      (is_add || is_reduce || is_delete || is_replace);

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

    wire [31:0]           dec       = (kind == K_REDUCE && m_shares < f_shares) ? m_shares : f_shares;
    wire [31:0]           left      = f_shares - dec;

    reg [SET_W-1:0] set_add;
    reg [SET_W-1:0] set_upd;

    always @(*) begin
        set_add = set_r;
        set_add[a_free*ENTRY_W +: ENTRY_W] = {1'b1, a_ref, a_side, m_lvl, m_shares};

        set_upd = set_r;
        set_upd[f_way*ENTRY_W +: ENTRY_W] = r_entry;
    end

    wire add_ok = a_nonzero && m_in_window && !a_full;

    wire [LEVEL_BITS-1:0] best_idx   = r_side ? bid_idx : ask_idx;
    wire                  at_best    = (r_lvl == best_idx);
    wire                  r_last     = r_side ? (r_lvl == {LEVEL_BITS{1'b0}}) : (&r_lvl);
    wire [LEVEL_BITS-1:0] r_next     = r_side ? r_lvl - 1'b1 : r_lvl + 1'b1;
    wire                  start_scan = at_best && r_emptied && !r_last;

    wire                  scan_hit   = (lvl_q != 32'd0);
    wire                  scan_last  = r_side ? (scan_idx == {LEVEL_BITS{1'b0}}) : (&scan_idx);
    wire [LEVEL_BITS-1:0] scan_next  = r_side ? scan_idx - 1'b1 : scan_idx + 1'b1;

    always @(*) begin
        ord_we    = 1'b0;
        ord_waddr = m_set;
        ord_wdata = set_upd;
        ord_re    = 1'b0;
        ord_raddr = set_of(order_ref[2*SET_BITS-1:0]);

        lvl_we    = 1'b0;
        lvl_waddr = {r_side, r_lvl};
        lvl_wdata = r_new_lvl;
        lvl_re    = 1'b0;
        lvl_raddr = {a_side, m_lvl};

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
                ord_re = for_us && !is_add;
            end

            S_REPLACE: begin
                ord_re    = 1'b1;
                ord_raddr = a_set;
                lvl_re    = 1'b1;
                lvl_raddr = {a_side, m_lvl};
            end

            S_ADD_WB: begin
                ord_we    = add_ok;
                ord_waddr = a_set;
                ord_wdata = set_add;
                lvl_we    = add_ok;
                lvl_waddr = {a_side, m_lvl};
                lvl_wdata = a_new_lvl;
            end

            S_REDUCE: begin
                lvl_re    = f_found;
                lvl_raddr = {f_side, f_lvl};
            end

            S_LEVEL: begin
                ord_we    = 1'b1;
                ord_waddr = m_set;
                ord_wdata = set_upd;
            end

            S_LEVEL_WB: begin
                lvl_we    = 1'b1;
                lvl_waddr = {r_side, r_lvl};
                lvl_wdata = r_new_lvl;
                lvl_re    = start_scan;
                lvl_raddr = {r_side, r_next};
            end

            S_SCAN: begin
                lvl_re    = 1'b1;
                lvl_raddr = {r_side, scan_next};
            end

            default: ;
        endcase
    end

    assign busy = (state != S_IDLE);

    wire [LEVEL_BITS-1:0] div_lvl = p_prod[22 +: LEVEL_BITS];
    wire                  unused  = &{1'b0, hit_entry[ENTRY_W-1 -: 65], p_diff[31:19], p_diff[1:0], p_prod[34], p_prod[21:0]};

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
            bid_price    <= 32'd0;
            ask_price    <= 32'd0;
            bid_qty      <= 32'd0;
            ask_qty      <= 32'd0;
            scan_price   <= 32'd0;
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
                        m_ref     <= order_ref;
                        m_new_ref <= new_order_ref;
                        m_set     <= set_of(order_ref[2*SET_BITS-1:0]);
                        m_shares  <= shares;
                        a_ref     <= order_ref;
                        a_set     <= set_of(order_ref[2*SET_BITS-1:0]);
                        a_side    <= side;
                        p_diff    <= price - base_price;
                        p_ge_base <= (price >= base_price);
                        if (is_add) begin
                            kind  <= K_ADD;
                            state <= S_DIV;
                        end else begin
                            kind  <= is_reduce ? K_REDUCE : is_delete ? K_DELETE : K_REPLACE;
                            state <= S_FIND;
                        end
                    end
                end

                S_DIV: begin
                    p_prod <= p_diff[18:2] * 18'd167773;
                    p_win  <= p_ge_base && (p_diff < WINDOW);
                    state  <= S_PREP;
                end

                S_PREP: begin
                    m_lvl       <= div_lvl;
                    m_in_window <= p_win;
                    m_lvl_price <= base_price + div_lvl * TICK;
                    state       <= S_REPLACE;
                end

                S_REPLACE: begin
                    state <= S_ADD;
                end

                S_ADD: begin
                    set_r     <= set_q;
                    a_free    <= free_way;
                    a_full    <= full;
                    a_nonzero <= (m_shares != 32'd0);
                    a_new_lvl <= lvl_q + m_shares;
                    state     <= S_ADD_WB;
                end

                S_ADD_WB: begin
                    if (!a_nonzero) begin
                    end else if (!m_in_window) begin
                        out_of_range <= out_of_range + 1'b1;
                    end else if (a_full) begin
                        collisions <= collisions + 1'b1;
                    end else if (a_side) begin
                        if (!bid_valid || m_lvl > bid_idx) begin
                            bid_valid <= 1'b1;
                            bid_idx   <= m_lvl;
                            bid_price <= m_lvl_price;
                            bid_qty   <= a_new_lvl;
                        end else if (m_lvl == bid_idx) begin
                            bid_qty <= a_new_lvl;
                        end
                    end else begin
                        if (!ask_valid || m_lvl < ask_idx) begin
                            ask_valid <= 1'b1;
                            ask_idx   <= m_lvl;
                            ask_price <= m_lvl_price;
                            ask_qty   <= a_new_lvl;
                        end else if (m_lvl == ask_idx) begin
                            ask_qty <= a_new_lvl;
                        end
                    end
                    book_update <= 1'b1;
                    state       <= S_IDLE;
                end

                S_FIND: begin
                    p_prod   <= p_diff[18:2] * 18'd167773;
                    p_win    <= p_ge_base && (p_diff < WINDOW);
                    set_r    <= set_q;
                    f_found  <= found;
                    f_way    <= hit_way;
                    f_side   <= e_side;
                    f_lvl    <= e_lvl;
                    f_shares <= e_shares;
                    state    <= S_REDUCE;
                end

                S_REDUCE: begin
                    m_lvl       <= div_lvl;
                    m_in_window <= p_win;
                    m_lvl_price <= base_price + div_lvl * TICK;
                    if (!f_found) begin
                        book_update <= 1'b1;
                        state       <= S_IDLE;
                    end else begin
                        r_side  <= f_side;
                        r_lvl   <= f_lvl;
                        r_dec   <= dec;
                        r_entry <= (left == 32'd0) ? {ENTRY_W{1'b0}}
                                                   : {1'b1, m_ref, f_side, f_lvl, left};
                        a_side  <= f_side;
                        a_ref   <= m_new_ref;
                        a_set   <= set_of(m_new_ref[2*SET_BITS-1:0]);
                        state   <= S_LEVEL;
                    end
                end

                S_LEVEL: begin
                    r_new_lvl <= lvl_q - r_dec;
                    r_emptied <= (lvl_q == r_dec);
                    state     <= S_LEVEL_WB;
                end

                S_LEVEL_WB: begin
                    if (start_scan) begin
                        scan_idx   <= r_next;
                        scan_price <= r_side ? (bid_price - TICK) : (ask_price + TICK);
                        state      <= S_SCAN;
                    end else begin
                        if (at_best && r_emptied) begin
                            if (r_side) bid_valid <= 1'b0;
                            else        ask_valid <= 1'b0;
                        end else if (at_best) begin
                            if (r_side) bid_qty <= r_new_lvl;
                            else        ask_qty <= r_new_lvl;
                        end
                        finish_reduce;
                    end
                end

                S_SCAN: begin
                    if (scan_hit) begin
                        if (r_side) begin
                            bid_idx   <= scan_idx;
                            bid_price <= scan_price;
                            bid_qty   <= lvl_q;
                        end else begin
                            ask_idx   <= scan_idx;
                            ask_price <= scan_price;
                            ask_qty   <= lvl_q;
                        end
                        finish_reduce;
                    end else if (scan_last) begin
                        if (r_side) bid_valid <= 1'b0;
                        else        ask_valid <= 1'b0;
                        finish_reduce;
                    end else begin
                        scan_idx   <= scan_next;
                        scan_price <= r_side ? (scan_price - TICK) : (scan_price + TICK);
                    end
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
