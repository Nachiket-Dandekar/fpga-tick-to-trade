module trigger (
    input  wire        clk,
    input  wire        rst,
    input  wire [31:0] limit_price,
    input  wire [31:0] max_qty,

    input  wire        book_update,
    input  wire        ask_valid,
    input  wire [31:0] ask_price,
    input  wire [31:0] ask_qty,

    output reg         order_valid,
    output reg  [31:0] order_price,
    output reg  [31:0] order_shares
);

    reg        prev_valid;
    reg [31:0] prev_price;

    wire changed = !prev_valid || (ask_price != prev_price);
    wire fire    = book_update && ask_valid && changed && (ask_price <= limit_price);

    always @(posedge clk) begin
        order_valid <= 1'b0;

        if (rst) begin
            prev_valid   <= 1'b0;
            prev_price   <= 32'd0;
            order_price  <= 32'd0;
            order_shares <= 32'd0;
        end else if (book_update) begin
            prev_valid <= ask_valid;
            prev_price <= ask_price;
            if (fire) begin
                order_valid  <= 1'b1;
                order_price  <= ask_price;
                order_shares <= (ask_qty < max_qty) ? ask_qty : max_qty;
            end
        end
    end

endmodule
