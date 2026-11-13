module uart_tx #(
    parameter CLKS_PER_BIT = 868
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       start,
    input  wire [7:0] data,
    output reg        tx,
    output wire       busy
);

    localparam [1:0] S_IDLE  = 2'd0;
    localparam [1:0] S_START = 2'd1;
    localparam [1:0] S_DATA  = 2'd2;
    localparam [1:0] S_STOP  = 2'd3;

    reg [1:0]  state;
    reg [15:0] clk_count;
    reg [2:0]  bit_index;
    reg [7:0]  shift;

    wire bit_done = (clk_count == CLKS_PER_BIT - 1);

    assign busy = (state != S_IDLE);

    always @(posedge clk) begin
        if (rst) begin
            state     <= S_IDLE;
            tx        <= 1'b1;
            clk_count <= 16'd0;
            bit_index <= 3'd0;
            shift     <= 8'd0;
        end else begin
            case (state)
                S_IDLE: begin
                    tx        <= 1'b1;
                    clk_count <= 16'd0;
                    bit_index <= 3'd0;
                    if (start) begin
                        shift <= data;
                        state <= S_START;
                    end
                end

                S_START: begin
                    tx <= 1'b0;
                    if (bit_done) begin
                        clk_count <= 16'd0;
                        state     <= S_DATA;
                    end else begin
                        clk_count <= clk_count + 16'd1;
                    end
                end

                S_DATA: begin
                    tx <= shift[0];
                    if (bit_done) begin
                        clk_count <= 16'd0;
                        shift     <= {1'b0, shift[7:1]};
                        if (bit_index == 3'd7)
                            state <= S_STOP;
                        else
                            bit_index <= bit_index + 3'd1;
                    end else begin
                        clk_count <= clk_count + 16'd1;
                    end
                end

                S_STOP: begin
                    tx <= 1'b1;
                    if (bit_done)
                        state <= S_IDLE;
                    else
                        clk_count <= clk_count + 16'd1;
                end
            endcase
        end
    end

endmodule
