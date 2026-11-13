module udp_strip #(
    parameter [15:0] UDP_PORT = 16'd26400
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        in_valid,
    input  wire [7:0]  in_data,
    input  wire        in_start,
    input  wire        in_end,

    output reg         out_valid,
    output reg  [7:0]  out_data,
    output reg         out_first,
    output reg         seq_gap,
    output reg  [31:0] frames_dropped,
    output reg  [31:0] seq_gaps
);

    localparam [15:0] AT_ETHERTYPE   = 16'd12;
    localparam [15:0] AT_IP_VERSION  = 16'd14;
    localparam [15:0] AT_IP_PROTOCOL = 16'd23;
    localparam [15:0] AT_UDP_START   = 16'd34;
    localparam [15:0] AT_DEST_PORT   = 16'd36;
    localparam [15:0] AT_UDP_LENGTH  = 16'd38;
    localparam [15:0] AT_SEQUENCE    = 16'd52;
    localparam [15:0] AT_COUNT       = 16'd60;
    localparam [15:0] AT_MESSAGES    = 16'd62;

    localparam [15:0] MIN_UDP_LENGTH = 16'd28;
    localparam [15:0] MAX_UDP_LENGTH = 16'd1480;

    localparam [1:0] S_IDLE    = 2'd0;
    localparam [1:0] S_HEADER  = 2'd1;
    localparam [1:0] S_PAYLOAD = 2'd2;
    localparam [1:0] S_SKIP    = 2'd3;

    reg [1:0]  state;
    reg [15:0] idx;
    reg [15:0] udp_length;
    reg [15:0] end_idx;
    reg [31:0] seq;
    reg [7:0]  count_hi;
    reg [31:0] expected_seq;
    reg        have_seq;
    reg        first;

    wire [15:0] msg_count = {count_hi, in_data};

    wire header_bad = (idx == AT_ETHERTYPE          && in_data != 8'h08) ||
                      (idx == AT_ETHERTYPE + 16'd1  && in_data != 8'h00) ||
                      (idx == AT_IP_VERSION         && in_data != 8'h45) ||
                      (idx == AT_IP_PROTOCOL        && in_data != 8'd17) ||
                      (idx == AT_DEST_PORT          && in_data != UDP_PORT[15:8]) ||
                      (idx == AT_DEST_PORT + 16'd1  && in_data != UDP_PORT[7:0]) ||
                      (idx == AT_COUNT + 16'd1      && udp_length < MIN_UDP_LENGTH) ||
                      (idx == AT_COUNT + 16'd1      && udp_length > MAX_UDP_LENGTH);

    always @(posedge clk) begin
        out_valid <= 1'b0;
        out_first <= 1'b0;
        seq_gap   <= 1'b0;

        if (rst) begin
            state          <= S_IDLE;
            idx            <= 16'd0;
            udp_length     <= 16'd0;
            end_idx        <= 16'd0;
            seq            <= 32'd0;
            count_hi       <= 8'd0;
            expected_seq   <= 32'd0;
            have_seq       <= 1'b0;
            first          <= 1'b0;
            out_data       <= 8'd0;
            frames_dropped <= 32'd0;
            seq_gaps       <= 32'd0;
        end else if (in_valid && in_start) begin
            idx   <= 16'd1;
            state <= S_HEADER;
        end else if (in_valid) begin
            idx <= idx + 16'd1;

            case (state)
                S_HEADER: begin
                    if (header_bad) begin
                        frames_dropped <= frames_dropped + 32'd1;
                        state          <= S_SKIP;
                    end else begin
                        if (idx == AT_UDP_LENGTH)
                            udp_length[15:8] <= in_data;
                        if (idx == AT_UDP_LENGTH + 16'd1) begin
                            udp_length[7:0] <= in_data;
                            end_idx         <= {udp_length[15:8], in_data} + AT_UDP_START;
                        end
                        if (idx >= AT_SEQUENCE && idx < AT_COUNT)
                            seq <= {seq[23:0], in_data};
                        if (idx == AT_COUNT)
                            count_hi <= in_data;
                        if (idx == AT_COUNT + 16'd1) begin
                            if (have_seq && seq != expected_seq) begin
                                seq_gap  <= 1'b1;
                                seq_gaps <= seq_gaps + 32'd1;
                            end
                            expected_seq <= seq + {16'd0, msg_count};
                            have_seq     <= 1'b1;
                            first        <= 1'b1;
                            if (end_idx == AT_MESSAGES)
                                state <= S_SKIP;
                            else
                                state <= S_PAYLOAD;
                        end
                    end
                end

                S_PAYLOAD: begin
                    out_valid <= 1'b1;
                    out_data  <= in_data;
                    out_first <= first;
                    first     <= 1'b0;
                    if (idx == end_idx - 16'd1)
                        state <= S_SKIP;
                end

                default: ;
            endcase
        end else if (in_end) begin
            if (state == S_HEADER)
                frames_dropped <= frames_dropped + 32'd1;
            state <= S_IDLE;
        end
    end

endmodule
