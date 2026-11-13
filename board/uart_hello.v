module uart_hello #(
    parameter CLKS_PER_BIT = 868,
    parameter PAUSE_CLKS   = 100_000_000
) (
    input  wire       clk,
    output wire       uart_txd,
    output reg  [3:0] led
);

    localparam LENGTH = 17;
    localparam [8*LENGTH-1:0] MESSAGE = "Hello from Arty\015\012";

    reg [3:0] startup = 4'd0;
    wire      rst     = !startup[3];

    always @(posedge clk) begin
        if (rst)
            startup <= startup + 4'd1;
    end

    reg [26:0] pause_count;
    reg [4:0]  index;
    reg        sending;
    reg        start;
    reg [7:0]  tx_data;
    wire       busy;

    wire [7:0] character = MESSAGE[8*(LENGTH - 1 - index) +: 8];

    always @(posedge clk) begin
        start <= 1'b0;

        if (rst) begin
            pause_count <= 27'd0;
            index       <= 5'd0;
            sending     <= 1'b0;
            tx_data     <= 8'd0;
            led         <= 4'd0;
        end else if (!sending) begin
            if (pause_count == PAUSE_CLKS - 1) begin
                pause_count <= 27'd0;
                index       <= 5'd0;
                sending     <= 1'b1;
                led         <= led + 4'd1;
            end else begin
                pause_count <= pause_count + 27'd1;
            end
        end else if (!busy && !start) begin
            if (index == LENGTH) begin
                sending <= 1'b0;
            end else begin
                tx_data <= character;
                start   <= 1'b1;
                index   <= index + 5'd1;
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
