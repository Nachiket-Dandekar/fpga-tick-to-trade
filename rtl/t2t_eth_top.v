module t2t_eth_top #(
    parameter [15:0] UDP_PORT    = 16'd26400,
    parameter        FIFO_ADDR   = 12,
    parameter [31:0] LIMIT_PRICE = 32'hFFFFFFFF,
    parameter [31:0] MAX_QTY     = 32'd500,
    parameter [63:0] STOCK       = "UN      "
) (
    input  wire        clk,
    input  wire        rx_clk,
    input  wire        tx_clk,
    input  wire        rst,
    input  wire        mii_rx_dv,
    input  wire [3:0]  mii_rxd,
    output wire        mii_tx_en,
    output wire [3:0]  mii_txd,
    output wire        tx_underrun,

    input  wire [15:0] target_locate,
    input  wire [31:0] base_price,

    output wire        book_update,
    output wire        bid_valid,
    output wire [31:0] bid_price,
    output wire [31:0] bid_qty,
    output wire        ask_valid,
    output wire [31:0] ask_price,
    output wire [31:0] ask_qty,
    output wire [15:0] collisions,
    output wire [15:0] out_of_range,

    output reg  [31:0] frames_ok,
    output reg  [31:0] crc_errors,
    output wire [31:0] frames_dropped,
    output wire [31:0] seq_gaps,
    output reg  [31:0] fifo_overflows,
    output reg  [31:0] msg_count,
    output reg  [15:0] fifo_max,

    output wire [31:0] orders_sent,
    output wire [31:0] orders_dropped,
    output wire [31:0] last_latency,
    output wire [31:0] min_latency,
    output wire [31:0] max_latency
);

    (* ASYNC_REG = "TRUE" *) reg [1:0] rx_rst_sync;
    (* ASYNC_REG = "TRUE" *) reg [1:0] rx_rst_seen;
    (* ASYNC_REG = "TRUE" *) reg [2:0] drop_sync;

    wire        rx_rst    = rx_rst_sync[1];
    wire        cross_rst = rst || rx_rst_seen[1];

    wire        mii_valid;
    wire [7:0]  mii_data;
    wire        mii_start;
    wire        mii_end;
    wire        mii_crc_ok;
    wire        mii_write = mii_valid || mii_end;

    wire        cross_full;
    wire        cross_empty;
    wire [11:0] cross_data;
    reg         drop_toggle;
    wire        cross_drop = drop_sync[2] ^ drop_sync[1];

    reg         rx_valid;
    reg  [7:0]  rx_data;
    reg         rx_start;
    reg         rx_end;
    reg         rx_crc_ok;

    wire        udp_valid;
    wire [7:0]  udp_data;
    wire        udp_first;
    wire        seq_gap;

    wire                 fifo_full;
    wire                 fifo_overflow;
    wire                 fifo_valid;
    wire [32:0]          fifo_data;
    wire [FIFO_ADDR:0]   fifo_level;
    wire [15:0]          fifo_fill = {{(15 - FIFO_ADDR){1'b0}}, fifo_level};

    reg  [23:0] cycle_cnt;
    reg  [23:0] udp_stamp;
    reg  [23:0] msg_stamp;
    reg  [23:0] book_stamp;
    reg  [31:0] book_msg_idx;
    reg  [23:0] trig_stamp;
    reg  [31:0] trig_msg_idx;

    wire        order_valid;
    wire [31:0] order_price;
    wire [31:0] order_shares;

    wire        busy;
    wire        byte_ready = !busy;
    wire        msg_valid;
    wire [7:0]  msg_type;
    wire [15:0] stock_locate;
    wire [63:0] order_ref;
    wire [63:0] new_order_ref;
    wire        side;
    wire [31:0] shares;
    wire [63:0] stock;
    wire [31:0] price;

    wire        unused = &{1'b0, seq_gap, fifo_full, stock};

    always @(posedge rx_clk) begin
        rx_rst_sync <= {rx_rst_sync[0], rst};
    end

    always @(posedge clk) begin
        rx_rst_seen <= {rx_rst_seen[0], rx_rst};
    end

    mii_rx rx (
        .clk          (rx_clk),
        .rst          (rx_rst),
        .mii_rx_dv    (mii_rx_dv),
        .mii_rxd      (mii_rxd),
        .byte_valid   (mii_valid),
        .byte_data    (mii_data),
        .frame_start  (mii_start),
        .frame_end    (mii_end),
        .frame_crc_ok (mii_crc_ok)
    );

    async_fifo #(.WIDTH(12)) rx_cross (
        .wr_clk  (rx_clk),
        .wr_rst  (rx_rst),
        .wr_en   (mii_write),
        .wr_data ({mii_valid, mii_end, mii_crc_ok, mii_start, mii_data}),
        .full    (cross_full),
        .rd_clk  (clk),
        .rd_rst  (cross_rst),
        .rd_en   (!cross_empty),
        .rd_data (cross_data),
        .empty   (cross_empty)
    );

    always @(posedge rx_clk) begin
        if (rx_rst)
            drop_toggle <= 1'b0;
        else if (mii_write && cross_full)
            drop_toggle <= !drop_toggle;
    end

    always @(posedge clk) begin
        if (cross_rst) begin
            drop_sync <= 3'd0;
            rx_valid  <= 1'b0;
            rx_data   <= 8'd0;
            rx_start  <= 1'b0;
            rx_end    <= 1'b0;
            rx_crc_ok <= 1'b0;
        end else begin
            drop_sync <= {drop_sync[1:0], drop_toggle};
            rx_valid  <= !cross_empty && cross_data[11];
            rx_end    <= !cross_empty && cross_data[10];
            rx_crc_ok <= cross_data[9];
            rx_start  <= cross_data[8];
            rx_data   <= cross_data[7:0];
        end
    end

    udp_strip #(.UDP_PORT(UDP_PORT)) strip (
        .clk            (clk),
        .rst            (rst),
        .in_valid       (rx_valid),
        .in_data        (rx_data),
        .in_start       (rx_start),
        .in_end         (rx_end),
        .out_valid      (udp_valid),
        .out_data       (udp_data),
        .out_first      (udp_first),
        .seq_gap        (seq_gap),
        .frames_dropped (frames_dropped),
        .seq_gaps       (seq_gaps)
    );

    sync_fifo #(.WIDTH(33), .ADDR(FIFO_ADDR)) fifo (
        .clk       (clk),
        .rst       (rst),
        .in_valid  (udp_valid),
        .in_data   ({udp_stamp, udp_first, udp_data}),
        .full      (fifo_full),
        .overflow  (fifo_overflow),
        .out_valid (fifo_valid),
        .out_data  (fifo_data),
        .out_ready (byte_ready),
        .level     (fifo_level)
    );

    itch_parser parser (
        .clk           (clk),
        .rst           (rst),
        .byte_valid    (fifo_valid && byte_ready),
        .byte_first    (fifo_data[8]),
        .byte_data     (fifo_data[7:0]),
        .msg_valid     (msg_valid),
        .msg_type      (msg_type),
        .stock_locate  (stock_locate),
        .order_ref     (order_ref),
        .new_order_ref (new_order_ref),
        .side          (side),
        .shares        (shares),
        .stock         (stock),
        .price         (price)
    );

    order_book book (
        .clk           (clk),
        .rst           (rst),
        .target_locate (target_locate),
        .base_price    (base_price),
        .msg_valid     (msg_valid),
        .msg_type      (msg_type),
        .stock_locate  (stock_locate),
        .order_ref     (order_ref),
        .new_order_ref (new_order_ref),
        .side          (side),
        .shares        (shares),
        .price         (price),
        .busy          (busy),
        .book_update   (book_update),
        .bid_valid     (bid_valid),
        .bid_price     (bid_price),
        .bid_qty       (bid_qty),
        .ask_valid     (ask_valid),
        .ask_price     (ask_price),
        .ask_qty       (ask_qty),
        .collisions    (collisions),
        .out_of_range  (out_of_range)
    );

    trigger trig (
        .clk          (clk),
        .rst          (rst),
        .limit_price  (LIMIT_PRICE),
        .max_qty      (MAX_QTY),
        .book_update  (book_update),
        .ask_valid    (ask_valid),
        .ask_price    (ask_price),
        .ask_qty      (ask_qty),
        .order_valid  (order_valid),
        .order_price  (order_price),
        .order_shares (order_shares)
    );

    order_tx #(.STOCK(STOCK)) tx_path (
        .clk            (clk),
        .tx_clk         (tx_clk),
        .rst            (rst),
        .cycle_cnt      (cycle_cnt),
        .order_valid    (order_valid),
        .order_price    (order_price),
        .order_shares   (order_shares),
        .order_stamp    (trig_stamp),
        .order_msg_idx  (trig_msg_idx),
        .mii_tx_en      (mii_tx_en),
        .mii_txd        (mii_txd),
        .tx_underrun    (tx_underrun),
        .orders_sent    (orders_sent),
        .orders_dropped (orders_dropped),
        .last_latency   (last_latency),
        .min_latency    (min_latency),
        .max_latency    (max_latency)
    );

    always @(posedge clk) begin
        if (rst) begin
            frames_ok      <= 32'd0;
            crc_errors     <= 32'd0;
            fifo_overflows <= 32'd0;
            msg_count      <= 32'd0;
            fifo_max       <= 16'd0;
            cycle_cnt      <= 24'd0;
            udp_stamp      <= 24'd0;
            msg_stamp      <= 24'd0;
            book_stamp     <= 24'd0;
            book_msg_idx   <= 32'd0;
            trig_stamp     <= 24'd0;
            trig_msg_idx   <= 32'd0;
        end else begin
            cycle_cnt <= cycle_cnt + 24'd1;
            udp_stamp <= cycle_cnt;
            if (fifo_valid && byte_ready)
                msg_stamp <= fifo_data[32:9];
            if (rx_end && rx_crc_ok)
                frames_ok <= frames_ok + 32'd1;
            if (rx_end && !rx_crc_ok)
                crc_errors <= crc_errors + 32'd1;
            if (fifo_overflow || cross_drop)
                fifo_overflows <= fifo_overflows + 32'd1;
            if (msg_valid) begin
                msg_count    <= msg_count + 32'd1;
                book_stamp   <= msg_stamp;
                book_msg_idx <= msg_count + 32'd1;
            end
            if (book_update) begin
                trig_stamp   <= book_stamp;
                trig_msg_idx <= book_msg_idx;
            end
            if (fifo_fill > fifo_max)
                fifo_max <= fifo_fill;
        end
    end

endmodule
