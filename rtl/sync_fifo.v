module sync_fifo #(
    parameter WIDTH = 9,
    parameter ADDR  = 12
) (
    input  wire             clk,
    input  wire             rst,

    input  wire             in_valid,
    input  wire [WIDTH-1:0] in_data,
    output wire             full,
    output reg              overflow,

    output reg              out_valid,
    output wire [WIDTH-1:0] out_data,
    input  wire             out_ready,

    output reg  [ADDR:0]    level
);

    reg [ADDR-1:0] wr_ptr;
    reg [ADDR-1:0] rd_ptr;

    assign full = level[ADDR];

    wire empty = (level == {(ADDR + 1){1'b0}});
    wire write = in_valid && !full;
    wire read  = !empty && (!out_valid || out_ready);

    ram_sdp #(.WIDTH(WIDTH), .ADDR(ADDR)) ram (
        .clk   (clk),
        .we    (write),
        .waddr (wr_ptr),
        .wdata (in_data),
        .re    (read),
        .raddr (rd_ptr),
        .rdata (out_data)
    );

    always @(posedge clk) begin
        overflow <= 1'b0;

        if (rst) begin
            wr_ptr    <= {ADDR{1'b0}};
            rd_ptr    <= {ADDR{1'b0}};
            level     <= {(ADDR + 1){1'b0}};
            out_valid <= 1'b0;
        end else begin
            if (write)
                wr_ptr <= wr_ptr + 1'b1;
            if (read)
                rd_ptr <= rd_ptr + 1'b1;

            if (write && !read)
                level <= level + 1'b1;
            else if (read && !write)
                level <= level - 1'b1;

            if (read)
                out_valid <= 1'b1;
            else if (out_ready)
                out_valid <= 1'b0;

            if (in_valid && full)
                overflow <= 1'b1;
        end
    end

endmodule
