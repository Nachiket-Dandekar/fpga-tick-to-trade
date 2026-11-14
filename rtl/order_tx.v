module order_tx #(
    parameter [63:0] STOCK = "UN      "
) (
    input  wire        clk,
    input  wire        tx_clk,
    input  wire        rst,

    input  wire [23:0] cycle_cnt,
    input  wire        order_valid,
    input  wire [31:0] order_price,
    input  wire [31:0] order_shares,
    input  wire [23:0] order_stamp,
    input  wire [31:0] order_msg_idx,

    output wire        mii_tx_en,
    output wire [3:0]  mii_txd,
    output wire        tx_underrun,

    output reg  [31:0] orders_sent,
    output reg  [31:0] orders_dropped,
    output reg  [31:0] last_latency,
    output reg  [31:0] min_latency,
    output reg  [31:0] max_latency
);

    localparam [1:0] S_IDLE = 2'd0;
    localparam [1:0] S_SEND = 2'd1;
    localparam [1:0] S_WAIT = 2'd2;

    (* ASYNC_REG = "TRUE" *) reg [1:0] tx_rst_sync;
    (* ASYNC_REG = "TRUE" *) reg [1:0] tx_rst_seen;
    (* ASYNC_REG = "TRUE" *) reg [2:0] done_sync;
    (* ASYNC_REG = "TRUE" *) reg [1:0] underrun_sync;

    wire tx_rst    = tx_rst_sync[1];
    wire cross_rst = rst || tx_rst_seen[1];
    wire tx_done   = done_sync[2] ^ done_sync[1];

    reg [119:0] q_mem [0:15];
    reg [3:0]   q_wr_ptr;
    reg [3:0]   q_rd_ptr;
    reg [4:0]   q_count;

    wire         q_full  = q_count[4];
    wire         q_empty = (q_count == 5'd0);
    wire [119:0] q_head  = q_mem[q_rd_ptr];

    reg [1:0]  state;
    reg [6:0]  byte_idx;
    reg [31:0] order_num;
    reg [31:0] cur_price;
    reg [31:0] cur_shares;
    reg [23:0] cur_stamp;
    reg [31:0] cur_msg_idx;
    reg [31:0] cur_latency;

    wire       tx_full;
    wire       tx_empty;
    wire [8:0] tx_data;
    wire       tx_rd_en;
    wire       mii_underrun;
    wire       done_toggle;

    wire q_push = order_valid && !q_full;
    wire q_pop  = (state == S_IDLE) && !q_empty && !tx_full;

    wire        tx_wr_en = (state == S_SEND) && !tx_full;
    wire        tx_last  = (byte_idx == 7'd98);
    reg  [7:0]  frame_byte;

    wire [23:0] lat_diff = cycle_cnt - cur_stamp;
    wire [31:0] lat_val  = {8'd0, lat_diff};

    assign tx_underrun = underrun_sync[1];

    function [7:0] hex_digit(input [3:0] n);
        hex_digit = (n < 4'd10) ? (8'h30 + {4'd0, n}) : (8'h37 + {4'd0, n});
    endfunction

    always @(*) begin
        case (byte_idx)
            7'd0, 7'd1, 7'd2, 7'd3, 7'd4, 7'd5: frame_byte = 8'hFF;
            7'd6:  frame_byte = 8'h02;
            7'd7, 7'd8, 7'd9, 7'd10: frame_byte = 8'h00;
            7'd11: frame_byte = 8'h01;
            7'd12: frame_byte = 8'h08;
            7'd13: frame_byte = 8'h00;
            7'd14: frame_byte = 8'h45;
            7'd15: frame_byte = 8'h00;
            7'd16: frame_byte = 8'h00;
            7'd17: frame_byte = 8'd85;
            7'd18: frame_byte = 8'h00;
            7'd19: frame_byte = 8'h00;
            7'd20: frame_byte = 8'h40;
            7'd21: frame_byte = 8'h00;
            7'd22: frame_byte = 8'd64;
            7'd23: frame_byte = 8'd17;
            7'd24: frame_byte = 8'h25;
            7'd25: frame_byte = 8'h98;
            7'd26: frame_byte = 8'd10;
            7'd27: frame_byte = 8'd0;
            7'd28: frame_byte = 8'd0;
            7'd29: frame_byte = 8'd2;
            7'd30: frame_byte = 8'd10;
            7'd31: frame_byte = 8'd0;
            7'd32: frame_byte = 8'd0;
            7'd33: frame_byte = 8'd255;
            7'd34: frame_byte = 8'h67;
            7'd35: frame_byte = 8'h21;
            7'd36: frame_byte = 8'h67;
            7'd37: frame_byte = 8'h21;
            7'd38: frame_byte = 8'h00;
            7'd39: frame_byte = 8'd65;
            7'd40: frame_byte = 8'h00;
            7'd41: frame_byte = 8'h00;
            7'd42: frame_byte = "O";
            7'd43: frame_byte = "T";
            7'd44: frame_byte = "2";
            7'd45: frame_byte = "T";
            7'd46: frame_byte = "0";
            7'd47: frame_byte = "0";
            7'd48: frame_byte = "0";
            7'd49: frame_byte = hex_digit(order_num[31:28]);
            7'd50: frame_byte = hex_digit(order_num[27:24]);
            7'd51: frame_byte = hex_digit(order_num[23:20]);
            7'd52: frame_byte = hex_digit(order_num[19:16]);
            7'd53: frame_byte = hex_digit(order_num[15:12]);
            7'd54: frame_byte = hex_digit(order_num[11:8]);
            7'd55: frame_byte = hex_digit(order_num[7:4]);
            7'd56: frame_byte = hex_digit(order_num[3:0]);
            7'd57: frame_byte = "B";
            7'd58: frame_byte = cur_shares[31:24];
            7'd59: frame_byte = cur_shares[23:16];
            7'd60: frame_byte = cur_shares[15:8];
            7'd61: frame_byte = cur_shares[7:0];
            7'd62: frame_byte = STOCK[63:56];
            7'd63: frame_byte = STOCK[55:48];
            7'd64: frame_byte = STOCK[47:40];
            7'd65: frame_byte = STOCK[39:32];
            7'd66: frame_byte = STOCK[31:24];
            7'd67: frame_byte = STOCK[23:16];
            7'd68: frame_byte = STOCK[15:8];
            7'd69: frame_byte = STOCK[7:0];
            7'd70: frame_byte = cur_price[31:24];
            7'd71: frame_byte = cur_price[23:16];
            7'd72: frame_byte = cur_price[15:8];
            7'd73: frame_byte = cur_price[7:0];
            7'd74, 7'd75, 7'd76, 7'd77: frame_byte = 8'h00;
            7'd78: frame_byte = "T";
            7'd79: frame_byte = "2";
            7'd80: frame_byte = "T";
            7'd81: frame_byte = " ";
            7'd82: frame_byte = "N";
            7'd83: frame_byte = "P";
            7'd84: frame_byte = "N";
            7'd85, 7'd86, 7'd87, 7'd88: frame_byte = 8'h00;
            7'd89: frame_byte = "N";
            7'd90: frame_byte = "N";
            7'd91: frame_byte = cur_latency[31:24];
            7'd92: frame_byte = cur_latency[23:16];
            7'd93: frame_byte = cur_latency[15:8];
            7'd94: frame_byte = cur_latency[7:0];
            7'd95: frame_byte = cur_msg_idx[31:24];
            7'd96: frame_byte = cur_msg_idx[23:16];
            7'd97: frame_byte = cur_msg_idx[15:8];
            7'd98: frame_byte = cur_msg_idx[7:0];
            default: frame_byte = 8'h00;
        endcase
    end

    always @(posedge tx_clk) begin
        tx_rst_sync <= {tx_rst_sync[0], rst};
    end

    always @(posedge clk) begin
        tx_rst_seen <= {tx_rst_seen[0], tx_rst};
    end

    always @(posedge clk) begin
        if (q_push)
            q_mem[q_wr_ptr] <= {order_price, order_shares, order_stamp, order_msg_idx};
    end

    always @(posedge clk) begin
        if (cross_rst) begin
            done_sync     <= 3'd0;
            underrun_sync <= 2'd0;
        end else begin
            done_sync     <= {done_sync[1:0], done_toggle};
            underrun_sync <= {underrun_sync[0], mii_underrun};
        end
    end

    always @(posedge clk) begin
        if (rst) begin
            q_wr_ptr       <= 4'd0;
            q_rd_ptr       <= 4'd0;
            q_count        <= 5'd0;
            state          <= S_IDLE;
            byte_idx       <= 7'd0;
            order_num      <= 32'd0;
            cur_price      <= 32'd0;
            cur_shares     <= 32'd0;
            cur_stamp      <= 24'd0;
            cur_msg_idx    <= 32'd0;
            cur_latency    <= 32'd0;
            orders_sent    <= 32'd0;
            orders_dropped <= 32'd0;
            last_latency   <= 32'd0;
            min_latency    <= 32'd0;
            max_latency    <= 32'd0;
        end else begin
            if (q_push)
                q_wr_ptr <= q_wr_ptr + 4'd1;
            if (q_pop)
                q_rd_ptr <= q_rd_ptr + 4'd1;

            if (q_push && !q_pop)
                q_count <= q_count + 5'd1;
            else if (q_pop && !q_push)
                q_count <= q_count - 5'd1;

            if (order_valid && q_full)
                orders_dropped <= orders_dropped + 32'd1;

            case (state)
                S_IDLE: begin
                    if (q_pop) begin
                        cur_price   <= q_head[119:88];
                        cur_shares  <= q_head[87:56];
                        cur_stamp   <= q_head[55:32];
                        cur_msg_idx <= q_head[31:0];
                        order_num   <= order_num + 32'd1;
                        byte_idx    <= 7'd0;
                        state       <= S_SEND;
                    end
                end

                S_SEND: begin
                    if (!tx_full) begin
                        if (byte_idx == 7'd0) begin
                            cur_latency  <= lat_val;
                            last_latency <= lat_val;
                            if (orders_sent == 32'd0 || lat_val < min_latency)
                                min_latency <= lat_val;
                            if (orders_sent == 32'd0 || lat_val > max_latency)
                                max_latency <= lat_val;
                            orders_sent <= orders_sent + 32'd1;
                        end
                        if (tx_last)
                            state <= S_WAIT;
                        else
                            byte_idx <= byte_idx + 7'd1;
                    end
                end

                S_WAIT: begin
                    if (tx_done)
                        state <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

    async_fifo #(.WIDTH(9)) tx_cross (
        .wr_clk  (clk),
        .wr_rst  (cross_rst),
        .wr_en   (tx_wr_en),
        .wr_data ({tx_last, frame_byte}),
        .full    (tx_full),
        .rd_clk  (tx_clk),
        .rd_rst  (tx_rst),
        .rd_en   (tx_rd_en),
        .rd_data (tx_data),
        .empty   (tx_empty)
    );

    mii_tx tx (
        .clk         (tx_clk),
        .rst         (tx_rst),
        .in_empty    (tx_empty),
        .in_data     (tx_data),
        .in_rd_en    (tx_rd_en),
        .mii_tx_en   (mii_tx_en),
        .mii_txd     (mii_txd),
        .tx_underrun (mii_underrun),
        .done_toggle (done_toggle)
    );

endmodule
