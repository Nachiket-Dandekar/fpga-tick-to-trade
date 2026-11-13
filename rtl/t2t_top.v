module t2t_top (
    input  wire        clk,
    input  wire        rst,
    input  wire        byte_valid,
    input  wire        byte_first,
    input  wire [7:0]  byte_data,
    output wire        byte_ready,

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
    output wire [15:0] out_of_range
);

    wire        busy;
    wire        msg_valid;
    wire [7:0]  msg_type;
    wire [15:0] stock_locate;
    wire [63:0] order_ref;
    wire [63:0] new_order_ref;
    wire        side;
    wire [31:0] shares;
    wire [63:0] stock;
    wire [31:0] price;

    assign byte_ready = !busy;

    itch_parser parser (
        .clk           (clk),
        .rst           (rst),
        .byte_valid    (byte_valid && byte_ready),
        .byte_first    (byte_first),
        .byte_data     (byte_data),
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

endmodule
