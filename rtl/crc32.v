module crc32 (
    input  wire [31:0] crc_in,
    input  wire [7:0]  data,
    output reg  [31:0] crc_out
);

    localparam [31:0] POLY = 32'hEDB88320;

    integer i;

    always @(*) begin
        crc_out = crc_in;
        for (i = 0; i < 8; i = i + 1) begin
            if (crc_out[0] ^ data[i])
                crc_out = (crc_out >> 1) ^ POLY;
            else
                crc_out = crc_out >> 1;
        end
    end

endmodule
