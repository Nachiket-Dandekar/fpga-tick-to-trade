`timescale 1ns / 1ps

module MMCME2_BASE #(
    parameter real    CLKIN1_PERIOD    = 10.0,
    parameter integer DIVCLK_DIVIDE    = 1,
    parameter real    CLKFBOUT_MULT_F  = 5.0,
    parameter real    CLKOUT0_DIVIDE_F = 1.0,
    parameter integer CLKOUT1_DIVIDE   = 1
) (
    input  wire CLKIN1,
    input  wire CLKFBIN,
    input  wire PWRDWN,
    input  wire RST,
    output reg  CLKFBOUT,
    output reg  CLKOUT0,
    output reg  CLKOUT1,
    output reg  LOCKED
);

    localparam real VCO_PERIOD = CLKIN1_PERIOD * DIVCLK_DIVIDE / CLKFBOUT_MULT_F;

    localparam real HALF_FB = VCO_PERIOD * CLKFBOUT_MULT_F / 2.0;
    localparam real HALF_0  = VCO_PERIOD * CLKOUT0_DIVIDE_F / 2.0;
    localparam real HALF_1  = VCO_PERIOD * CLKOUT1_DIVIDE / 2.0;

    integer edges;

    initial begin
        LOCKED = 1'b0;
        edges  = 0;
    end

    always @(posedge CLKIN1) begin
        if (RST || PWRDWN) begin
            edges  <= 0;
            LOCKED <= 1'b0;
        end else if (edges < 50) begin
            edges <= edges + 1;
        end else begin
            LOCKED <= 1'b1;
        end
    end

    initial begin
        CLKFBOUT = 1'b0;
        @(posedge CLKIN1);
        forever begin
            CLKFBOUT = 1'b1;
            #(HALF_FB);
            CLKFBOUT = 1'b0;
            #(HALF_FB);
        end
    end

    initial begin
        CLKOUT0 = 1'b0;
        @(posedge CLKIN1);
        forever begin
            CLKOUT0 = 1'b1;
            #(HALF_0);
            CLKOUT0 = 1'b0;
            #(HALF_0);
        end
    end

    initial begin
        CLKOUT1 = 1'b0;
        @(posedge CLKIN1);
        forever begin
            CLKOUT1 = 1'b1;
            #(HALF_1);
            CLKOUT1 = 1'b0;
            #(HALF_1);
        end
    end

endmodule

module BUFG (
    input  wire I,
    output wire O
);

    assign O = I;

endmodule

module ODDR #(
    parameter DDR_CLK_EDGE = "OPPOSITE_EDGE"
) (
    output reg  Q,
    input  wire C,
    input  wire CE,
    input  wire D1,
    input  wire D2,
    input  wire R,
    input  wire S
);

    initial Q = 1'b0;

    always @(posedge C) begin
        if (R)
            Q <= 1'b0;
        else if (S)
            Q <= 1'b1;
        else if (CE)
            Q <= D1;
    end

    always @(negedge C) begin
        if (R)
            Q <= 1'b0;
        else if (S)
            Q <= 1'b1;
        else if (CE)
            Q <= D2;
    end

endmodule
