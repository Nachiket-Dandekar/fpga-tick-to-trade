module mii_rx (
    input  wire       clk,
    input  wire       rst,
    input  wire       mii_rx_dv,
    input  wire [3:0] mii_rxd,

    output reg        byte_valid,
    output reg  [7:0] byte_data,
    output reg        frame_start,
    output reg        frame_end,
    output reg        frame_crc_ok
);

    localparam [31:0] CRC_INIT    = 32'hFFFFFFFF;
    localparam [31:0] CRC_RESIDUE = 32'hDEBB20E3;

    localparam [1:0] S_SKIP = 2'd0;
    localparam [1:0] S_IDLE = 2'd1;
    localparam [1:0] S_LOW  = 2'd2;
    localparam [1:0] S_HIGH = 2'd3;

    reg [1:0]   state;
    reg         dv;
    reg [3:0]   rxd;
    reg [3:0]   low_nibble;
    reg         first;
    reg [31:0]  crc;
    wire [31:0] crc_next;

    crc32 crc_byte (
        .crc_in  (crc),
        .data    ({rxd, low_nibble}),
        .crc_out (crc_next)
    );

    always @(posedge clk) begin
        dv          <= mii_rx_dv;
        rxd         <= mii_rxd;
        byte_valid  <= 1'b0;
        frame_start <= 1'b0;
        frame_end   <= 1'b0;

        if (rst) begin
            state        <= S_SKIP;
            low_nibble   <= 4'd0;
            first        <= 1'b0;
            crc          <= CRC_INIT;
            byte_data    <= 8'd0;
            frame_crc_ok <= 1'b0;
        end else begin
            case (state)
                S_SKIP: begin
                    if (!dv)
                        state <= S_IDLE;
                end

                S_IDLE: begin
                    if (dv && rxd == 4'hD) begin
                        crc   <= CRC_INIT;
                        first <= 1'b1;
                        state <= S_LOW;
                    end else if (dv && rxd != 4'h5) begin
                        state <= S_SKIP;
                    end
                end

                S_LOW: begin
                    if (!dv) begin
                        frame_end    <= 1'b1;
                        frame_crc_ok <= (crc == CRC_RESIDUE);
                        state        <= S_IDLE;
                    end else begin
                        low_nibble <= rxd;
                        state      <= S_HIGH;
                    end
                end

                S_HIGH: begin
                    if (!dv) begin
                        frame_end    <= 1'b1;
                        frame_crc_ok <= 1'b0;
                        state        <= S_IDLE;
                    end else begin
                        byte_valid  <= 1'b1;
                        byte_data   <= {rxd, low_nibble};
                        frame_start <= first;
                        first       <= 1'b0;
                        crc         <= crc_next;
                        state       <= S_LOW;
                    end
                end

                default: state <= S_SKIP;
            endcase
        end
    end

endmodule
