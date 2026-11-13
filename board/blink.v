module blink (
    input  wire       clk,
    output reg  [3:0] led = 4'd0
);

    localparam [25:0] HALF_SECOND = 26'd49_999_999;

    reg [25:0] count = 26'd0;

    always @(posedge clk) begin
        if (count == HALF_SECOND) begin
            count <= 26'd0;
            led   <= led + 4'd1;
        end else begin
            count <= count + 26'd1;
        end
    end

endmodule
