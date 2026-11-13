module status_uart #(
    parameter CLKS_PER_BIT = 868,
    parameter PERIOD_CLKS  = 100_000_000
) (
    input  wire        clk,
    input  wire        rst,

    input  wire [31:0] frames_ok,
    input  wire [31:0] crc_errors,
    input  wire [31:0] frames_dropped,
    input  wire [31:0] seq_gaps,
    input  wire [31:0] fifo_overflows,
    input  wire [31:0] msg_count,
    input  wire [15:0] fifo_max,
    input  wire [15:0] collisions,
    input  wire [15:0] out_of_range,
    input  wire        bid_valid,
    input  wire [31:0] bid_price,
    input  wire [31:0] bid_qty,
    input  wire        ask_valid,
    input  wire [31:0] ask_price,
    input  wire [31:0] ask_qty,

    output wire        uart_txd
);

    localparam [7:0] LENGTH = 8'd154;
    localparam [7:0] DIGITS = 8'd94;

    localparam [8*LENGTH-1:0] TEMPLATE = {
        "ok=######## crc=######## drop=######## gap=######## ovf=######## msg=######## ",
        "max=#### col=#### oor=#### bid=# ######## ######## ask=# ######## ########\015\012"};

    function [7:0] hex_digit(input [3:0] n);
        hex_digit = (n < 4'd10) ? 8'h30 + {4'd0, n} : 8'h37 + {4'd0, n};
    endfunction

    reg [31:0]         period_count;
    reg [4*DIGITS-1:0] digits;
    reg [7:0]          index;
    reg                sending;
    reg                start;
    reg [7:0]          tx_data;
    wire               busy;

    wire [7:0] character = TEMPLATE[8*(LENGTH - 1 - index) +: 8];

    always @(posedge clk) begin
        start <= 1'b0;

        if (rst) begin
            period_count <= 32'd0;
            index        <= 8'd0;
            sending      <= 1'b0;
            tx_data      <= 8'd0;
        end else begin
            if (period_count == PERIOD_CLKS - 1)
                period_count <= 32'd0;
            else
                period_count <= period_count + 32'd1;

            if (!sending) begin
                if (period_count == PERIOD_CLKS - 1) begin
                    digits  <= {frames_ok, crc_errors, frames_dropped, seq_gaps, fifo_overflows,
                                msg_count, fifo_max, collisions, out_of_range,
                                3'd0, bid_valid, bid_price, bid_qty,
                                3'd0, ask_valid, ask_price, ask_qty};
                    index   <= 8'd0;
                    sending <= 1'b1;
                end
            end else if (!busy && !start) begin
                if (index == LENGTH) begin
                    sending <= 1'b0;
                end else begin
                    if (character == "#") begin
                        tx_data <= hex_digit(digits[4*DIGITS-1 -: 4]);
                        digits  <= digits << 4;
                    end else begin
                        tx_data <= character;
                    end
                    start <= 1'b1;
                    index <= index + 8'd1;
                end
            end
        end
    end

    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) transmitter (
        .clk   (clk),
        .rst   (rst),
        .start (start),
        .data  (tx_data),
        .tx    (uart_txd),
        .busy  (busy)
    );

endmodule
