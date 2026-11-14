module mii_tx (
    input  wire       clk,
    input  wire       rst,
    input  wire       in_empty,
    input  wire [8:0] in_data,
    output wire       in_rd_en,

    (* IOB = "TRUE" *) output reg       mii_tx_en,
    (* IOB = "TRUE" *) output reg [3:0] mii_txd,
    output reg        tx_underrun,
    output reg        done_toggle
);

    localparam [31:0] CRC_INIT   = 32'hFFFFFFFF;
    localparam [4:0]  IFG_CYCLES = 5'd23;

    localparam [2:0] S_IDLE = 3'd0;
    localparam [2:0] S_PRE  = 3'd1;
    localparam [2:0] S_LO   = 3'd2;
    localparam [2:0] S_HI   = 3'd3;
    localparam [2:0] S_FCS  = 3'd4;
    localparam [2:0] S_IFG  = 3'd5;

    reg [2:0]   state;
    reg [4:0]   cnt;
    reg [7:0]   cur_byte;
    reg         cur_last;
    reg [31:0]  crc;
    wire [31:0] crc_next;

    assign in_rd_en = (state == S_LO);

    crc32 crc_inst (
        .crc_in  (crc),
        .data    (cur_byte),
        .crc_out (crc_next)
    );

    always @(posedge clk) begin
        if (rst) begin
            state       <= S_IDLE;
            cnt         <= 5'd0;
            cur_byte    <= 8'd0;
            cur_last    <= 1'b0;
            crc         <= CRC_INIT;
            mii_tx_en   <= 1'b0;
            mii_txd     <= 4'd0;
            tx_underrun <= 1'b0;
            done_toggle <= 1'b0;
        end else begin
            case (state)
                S_IDLE: begin
                    mii_tx_en <= 1'b0;
                    mii_txd   <= 4'd0;
                    if (!in_empty) begin
                        mii_tx_en <= 1'b1;
                        mii_txd   <= 4'h5;
                        cnt       <= 5'd1;
                        crc       <= CRC_INIT;
                        state     <= S_PRE;
                    end
                end

                S_PRE: begin
                    mii_tx_en <= 1'b1;
                    if (cnt == 5'd15) begin
                        mii_txd <= 4'hD;
                        state   <= S_LO;
                    end else begin
                        mii_txd <= 4'h5;
                        cnt     <= cnt + 5'd1;
                    end
                end

                S_LO: begin
                    if (in_empty)
                        tx_underrun <= 1'b1;
                    mii_tx_en <= 1'b1;
                    mii_txd   <= in_data[3:0];
                    cur_byte  <= in_data[7:0];
                    cur_last  <= in_data[8];
                    state     <= S_HI;
                end

                S_HI: begin
                    mii_tx_en <= 1'b1;
                    mii_txd   <= cur_byte[7:4];
                    crc       <= crc_next;
                    if (cur_last) begin
                        cnt   <= 5'd0;
                        state <= S_FCS;
                    end else begin
                        state <= S_LO;
                    end
                end

                S_FCS: begin
                    mii_tx_en <= 1'b1;
                    mii_txd   <= ~crc[3:0];
                    crc       <= {4'd0, crc[31:4]};
                    if (cnt == 5'd7) begin
                        cnt   <= 5'd0;
                        state <= S_IFG;
                    end else begin
                        cnt <= cnt + 5'd1;
                    end
                end

                S_IFG: begin
                    mii_tx_en <= 1'b0;
                    mii_txd   <= 4'd0;
                    if (cnt == IFG_CYCLES - 5'd3)
                        done_toggle <= !done_toggle;
                    if (cnt == IFG_CYCLES) begin
                        state <= S_IDLE;
                    end else begin
                        cnt <= cnt + 5'd1;
                    end
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
