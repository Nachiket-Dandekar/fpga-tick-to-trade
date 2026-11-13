module ram_sdp #(
    parameter WIDTH = 32,
    parameter ADDR  = 10
) (
    input  wire             clk,
    input  wire             we,
    input  wire [ADDR-1:0]  waddr,
    input  wire [WIDTH-1:0] wdata,
    input  wire             re,
    input  wire [ADDR-1:0]  raddr,
    output reg  [WIDTH-1:0] rdata
);

    (* ram_style = "block" *)
    reg [WIDTH-1:0] mem [0:(1 << ADDR) - 1];

    always @(posedge clk) begin
        if (we)
            mem[waddr] <= wdata;
        if (re)
            rdata <= mem[raddr];
    end

endmodule
