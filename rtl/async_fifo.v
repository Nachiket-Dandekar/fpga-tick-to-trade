module async_fifo #(
    parameter WIDTH = 8
) (
    input  wire             wr_clk,
    input  wire             wr_rst,
    input  wire             wr_en,
    input  wire [WIDTH-1:0] wr_data,
    output wire             full,

    input  wire             rd_clk,
    input  wire             rd_rst,
    input  wire             rd_en,
    output wire [WIDTH-1:0] rd_data,
    output wire             empty
);

    localparam ADDR  = 4;
    localparam DEPTH = 1 << ADDR;

    reg [WIDTH-1:0] mem [0:DEPTH-1];

    reg [ADDR:0] wr_bin;
    reg [ADDR:0] wr_gray;
    reg [ADDR:0] rd_bin;
    reg [ADDR:0] rd_gray;

    (* ASYNC_REG = "TRUE" *) reg [ADDR:0] rd_gray_s1;
    (* ASYNC_REG = "TRUE" *) reg [ADDR:0] rd_gray_s2;
    (* ASYNC_REG = "TRUE" *) reg [ADDR:0] wr_gray_s1;
    (* ASYNC_REG = "TRUE" *) reg [ADDR:0] wr_gray_s2;

    wire [ADDR:0] wr_bin_next  = wr_bin + 1'b1;
    wire [ADDR:0] wr_gray_next = wr_bin_next ^ (wr_bin_next >> 1);
    wire [ADDR:0] rd_bin_next  = rd_bin + 1'b1;
    wire [ADDR:0] rd_gray_next = rd_bin_next ^ (rd_bin_next >> 1);

    assign full  = (wr_gray == {~rd_gray_s2[ADDR:ADDR-1], rd_gray_s2[ADDR-2:0]});
    assign empty = (rd_gray == wr_gray_s2);

    wire write = wr_en && !full;
    wire read  = rd_en && !empty;

    assign rd_data = mem[rd_bin[ADDR-1:0]];

    always @(posedge wr_clk) begin
        if (write)
            mem[wr_bin[ADDR-1:0]] <= wr_data;
    end

    always @(posedge wr_clk) begin
        if (wr_rst) begin
            wr_bin     <= {(ADDR + 1){1'b0}};
            wr_gray    <= {(ADDR + 1){1'b0}};
            rd_gray_s1 <= {(ADDR + 1){1'b0}};
            rd_gray_s2 <= {(ADDR + 1){1'b0}};
        end else begin
            rd_gray_s1 <= rd_gray;
            rd_gray_s2 <= rd_gray_s1;
            if (write) begin
                wr_bin  <= wr_bin_next;
                wr_gray <= wr_gray_next;
            end
        end
    end

    always @(posedge rd_clk) begin
        if (rd_rst) begin
            rd_bin     <= {(ADDR + 1){1'b0}};
            rd_gray    <= {(ADDR + 1){1'b0}};
            wr_gray_s1 <= {(ADDR + 1){1'b0}};
            wr_gray_s2 <= {(ADDR + 1){1'b0}};
        end else begin
            wr_gray_s1 <= wr_gray;
            wr_gray_s2 <= wr_gray_s1;
            if (read) begin
                rd_bin  <= rd_bin_next;
                rd_gray <= rd_gray_next;
            end
        end
    end

endmodule
