module arty_t2t_top #(
    parameter [15:0] TARGET_LOCATE = 16'd8162,
    parameter [31:0] BASE_PRICE    = 32'd374300,
    parameter        BAUD          = 115_200,
    parameter        STATUS_HZ     = 1,
    parameter        PHY_RESET_US  = 10_000
) (
    input  wire       clk,
    input  wire       btn_rst,
    output wire       uart_txd,
    output reg  [3:0] led,

    output wire       eth_ref_clk,
    output reg        eth_rstn,
    input  wire       eth_rx_clk,
    input  wire       eth_rx_dv,
    input  wire [3:0] eth_rxd,
    input  wire       eth_rxerr,
    input  wire       eth_col,
    input  wire       eth_crs,
    input  wire       eth_tx_clk,
    output wire       eth_tx_en,
    output wire [3:0] eth_txd,
    output wire       eth_mdc,
    inout  wire       eth_mdio
);

    localparam SYS_DIV      = 16;
    localparam SYS_HZ       = 800_000_000 / SYS_DIV;
    localparam CLKS_PER_BIT = SYS_HZ / BAUD;
    localparam PERIOD_CLKS  = SYS_HZ / STATUS_HZ;
    localparam RESET_CLKS   = SYS_HZ / 1_000_000 * PHY_RESET_US;
    localparam BLINK_CLKS   = SYS_HZ / 2;
    localparam FLASH_CLKS   = SYS_HZ / 20;

    assign eth_tx_en = 1'b0;
    assign eth_txd   = 4'd0;
    assign eth_mdc   = 1'b0;
    assign eth_mdio  = 1'bz;

    wire clk_fb_raw;
    wire clk_fb;
    wire clk_sys_raw;
    wire clk_sys;
    wire clk_25_raw;
    wire clk_25;
    wire rx_clk;
    wire locked;

    MMCME2_BASE #(
        .CLKIN1_PERIOD    (10.0),
        .DIVCLK_DIVIDE    (1),
        .CLKFBOUT_MULT_F  (8.0),
        .CLKOUT0_DIVIDE_F (SYS_DIV),
        .CLKOUT1_DIVIDE   (32)
    ) mmcm (
        .CLKIN1   (clk),
        .CLKFBIN  (clk_fb),
        .CLKFBOUT (clk_fb_raw),
        .CLKOUT0  (clk_sys_raw),
        .CLKOUT1  (clk_25_raw),
        .LOCKED   (locked),
        .PWRDWN   (1'b0),
        .RST      (1'b0)
    );

    BUFG fb_buf  (.I(clk_fb_raw),  .O(clk_fb));
    BUFG sys_buf (.I(clk_sys_raw), .O(clk_sys));
    BUFG ref_buf (.I(clk_25_raw),  .O(clk_25));
    BUFG rx_buf  (.I(eth_rx_clk),  .O(rx_clk));

    ODDR #(.DDR_CLK_EDGE("SAME_EDGE")) ref_out (
        .Q  (eth_ref_clk),
        .C  (clk_25),
        .CE (1'b1),
        .D1 (1'b1),
        .D2 (1'b0),
        .R  (1'b0),
        .S  (1'b0)
    );

    (* ASYNC_REG = "TRUE" *) reg [1:0] locked_sync = 2'b00;
    (* ASYNC_REG = "TRUE" *) reg [1:0] btn_sync    = 2'b00;

    wire restart = !locked_sync[1] || btn_sync[1];

    reg [31:0] reset_count = 32'd0;
    reg        rst         = 1'b1;

    initial eth_rstn = 1'b0;

    always @(posedge clk_sys) begin
        locked_sync <= {locked_sync[0], locked};
        btn_sync    <= {btn_sync[0], btn_rst};
    end

    always @(posedge clk_sys) begin
        if (restart) begin
            reset_count <= 32'd0;
            eth_rstn    <= 1'b0;
            rst         <= 1'b1;
        end else if (reset_count != 2 * RESET_CLKS) begin
            reset_count <= reset_count + 32'd1;
            eth_rstn    <= (reset_count >= RESET_CLKS);
            rst         <= 1'b1;
        end else begin
            rst <= 1'b0;
        end
    end

    wire        book_update;
    wire        bid_valid;
    wire [31:0] bid_price;
    wire [31:0] bid_qty;
    wire        ask_valid;
    wire [31:0] ask_price;
    wire [31:0] ask_qty;
    wire [15:0] collisions;
    wire [15:0] out_of_range;
    wire [31:0] frames_ok;
    wire [31:0] crc_errors;
    wire [31:0] frames_dropped;
    wire [31:0] seq_gaps;
    wire [31:0] fifo_overflows;
    wire [31:0] msg_count;
    wire [15:0] fifo_max;

    wire        unused = &{1'b0, eth_rxerr, eth_col, eth_crs, eth_tx_clk, book_update};

    t2t_eth_top #(.UDP_PORT(16'd26400)) eth (
        .clk            (clk_sys),
        .rx_clk         (rx_clk),
        .rst            (rst),
        .mii_rx_dv      (eth_rx_dv),
        .mii_rxd        (eth_rxd),
        .target_locate  (TARGET_LOCATE),
        .base_price     (BASE_PRICE),
        .book_update    (book_update),
        .bid_valid      (bid_valid),
        .bid_price      (bid_price),
        .bid_qty        (bid_qty),
        .ask_valid      (ask_valid),
        .ask_price      (ask_price),
        .ask_qty        (ask_qty),
        .collisions     (collisions),
        .out_of_range   (out_of_range),
        .frames_ok      (frames_ok),
        .crc_errors     (crc_errors),
        .frames_dropped (frames_dropped),
        .seq_gaps       (seq_gaps),
        .fifo_overflows (fifo_overflows),
        .msg_count      (msg_count),
        .fifo_max       (fifo_max)
    );

    status_uart #(
        .CLKS_PER_BIT (CLKS_PER_BIT),
        .PERIOD_CLKS  (PERIOD_CLKS)
    ) status (
        .clk            (clk_sys),
        .rst            (rst),
        .frames_ok      (frames_ok),
        .crc_errors     (crc_errors),
        .frames_dropped (frames_dropped),
        .seq_gaps       (seq_gaps),
        .fifo_overflows (fifo_overflows),
        .msg_count      (msg_count),
        .fifo_max       (fifo_max),
        .collisions     (collisions),
        .out_of_range   (out_of_range),
        .bid_valid      (bid_valid),
        .bid_price      (bid_valid ? bid_price : 32'd0),
        .bid_qty        (bid_valid ? bid_qty : 32'd0),
        .ask_valid      (ask_valid),
        .ask_price      (ask_valid ? ask_price : 32'd0),
        .ask_qty        (ask_valid ? ask_qty : 32'd0),
        .uart_txd       (uart_txd)
    );

    reg [31:0] blink_count = 32'd0;
    reg        blink       = 1'b0;
    reg [31:0] flash_count;
    reg [31:0] last_frames;

    always @(posedge clk_sys) begin
        if (blink_count == BLINK_CLKS - 1) begin
            blink_count <= 32'd0;
            blink       <= !blink;
        end else begin
            blink_count <= blink_count + 32'd1;
        end
    end

    always @(posedge clk_sys) begin
        if (rst) begin
            flash_count <= 32'd0;
            last_frames <= 32'd0;
            led         <= 4'd0;
        end else begin
            last_frames <= frames_ok;
            if (frames_ok != last_frames)
                flash_count <= FLASH_CLKS;
            else if (flash_count != 32'd0)
                flash_count <= flash_count - 32'd1;

            led[0] <= blink;
            led[1] <= (flash_count != 32'd0);
            led[2] <= bid_valid && ask_valid;
            led[3] <= (crc_errors != 32'd0) || (seq_gaps != 32'd0) || (fifo_overflows != 32'd0);
        end
    end

endmodule
