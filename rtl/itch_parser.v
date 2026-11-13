module itch_parser (
    input  wire        clk,
    input  wire        rst,
    input  wire        byte_valid,
    input  wire        byte_first,
    input  wire [7:0]  byte_data,

    output reg         msg_valid,
    output reg  [7:0]  msg_type,
    output reg  [15:0] stock_locate,
    output reg  [63:0] order_ref,
    output reg  [63:0] new_order_ref,
    output reg         side,
    output reg  [31:0] shares,
    output reg  [63:0] stock,
    output reg  [31:0] price
);

    localparam [7:0] T_ADD      = "A";
    localparam [7:0] T_ADD_ATTR = "F";
    localparam [7:0] T_EXEC     = "E";
    localparam [7:0] T_EXEC_PX  = "C";
    localparam [7:0] T_CANCEL   = "X";
    localparam [7:0] T_DELETE   = "D";
    localparam [7:0] T_REPLACE  = "U";

    localparam [1:0] S_LEN_HI = 2'd0;
    localparam [1:0] S_LEN_LO = 2'd1;
    localparam [1:0] S_BODY   = 2'd2;

    reg [1:0]  state;
    reg [15:0] len;
    reg [15:0] idx;

    always @(posedge clk) begin
        msg_valid <= 1'b0;

        if (rst) begin
            state         <= S_LEN_HI;
            len           <= 16'd0;
            idx           <= 16'd0;
            msg_type      <= 8'd0;
            stock_locate  <= 16'd0;
            order_ref     <= 64'd0;
            new_order_ref <= 64'd0;
            side          <= 1'b0;
            shares        <= 32'd0;
            stock         <= 64'd0;
            price         <= 32'd0;
        end else if (byte_valid && byte_first) begin
            len   <= {byte_data, 8'd0};
            state <= S_LEN_LO;
        end else if (byte_valid) begin
            case (state)
                S_LEN_HI: begin
                    len   <= {byte_data, 8'd0};
                    state <= S_LEN_LO;
                end

                S_LEN_LO: begin
                    len <= {len[15:8], byte_data};
                    idx <= 16'd0;
                    if ({len[15:8], byte_data} == 16'd0)
                        state <= S_LEN_HI;
                    else
                        state <= S_BODY;
                end

                S_BODY: begin
                    if (idx == 16'd0) begin
                        msg_type      <= byte_data;
                        stock_locate  <= 16'd0;
                        order_ref     <= 64'd0;
                        new_order_ref <= 64'd0;
                        side          <= 1'b0;
                        shares        <= 32'd0;
                        stock         <= 64'd0;
                        price         <= 32'd0;
                    end else begin
                        if (idx >= 1 && idx <= 2)
                            stock_locate <= {stock_locate[7:0], byte_data};

                        case (msg_type)
                            T_ADD, T_ADD_ATTR: begin
                                if (idx >= 11 && idx <= 18) order_ref <= {order_ref[55:0], byte_data};
                                if (idx == 19)              side      <= (byte_data == "B");
                                if (idx >= 20 && idx <= 23) shares    <= {shares[23:0], byte_data};
                                if (idx >= 24 && idx <= 31) stock     <= {stock[55:0], byte_data};
                                if (idx >= 32 && idx <= 35) price     <= {price[23:0], byte_data};
                            end

                            T_EXEC, T_EXEC_PX, T_CANCEL: begin
                                if (idx >= 11 && idx <= 18) order_ref <= {order_ref[55:0], byte_data};
                                if (idx >= 19 && idx <= 22) shares    <= {shares[23:0], byte_data};
                            end

                            T_DELETE: begin
                                if (idx >= 11 && idx <= 18) order_ref <= {order_ref[55:0], byte_data};
                            end

                            T_REPLACE: begin
                                if (idx >= 11 && idx <= 18) order_ref     <= {order_ref[55:0], byte_data};
                                if (idx >= 19 && idx <= 26) new_order_ref <= {new_order_ref[55:0], byte_data};
                                if (idx >= 27 && idx <= 30) shares        <= {shares[23:0], byte_data};
                                if (idx >= 31 && idx <= 34) price         <= {price[23:0], byte_data};
                            end

                            default: ;
                        endcase
                    end

                    if (idx == len - 16'd1) begin
                        msg_valid <= 1'b1;
                        state     <= S_LEN_HI;
                    end else begin
                        idx <= idx + 16'd1;
                    end
                end

                default: state <= S_LEN_HI;
            endcase
        end
    end

endmodule
