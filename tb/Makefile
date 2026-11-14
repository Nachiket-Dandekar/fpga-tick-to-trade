SIM ?= icarus
TOPLEVEL_LANG = verilog
TOP ?= parser
FIFO_ADDR ?= 4

RTL = $(PWD)/../rtl
BOARD = $(PWD)/../board
ETH_SOURCES = $(RTL)/crc32.v $(RTL)/mii_rx.v $(RTL)/async_fifo.v $(RTL)/udp_strip.v $(RTL)/ram_sdp.v \
              $(RTL)/sync_fifo.v $(RTL)/itch_parser.v $(RTL)/order_book.v $(RTL)/trigger.v \
              $(RTL)/mii_tx.v $(RTL)/order_tx.v $(RTL)/t2t_eth_top.v

ifeq ($(TOP),book)
VERILOG_SOURCES = $(RTL)/itch_parser.v $(RTL)/ram_sdp.v $(RTL)/order_book.v $(RTL)/t2t_top.v
COCOTB_TOPLEVEL = t2t_top
COCOTB_TEST_MODULES = test_order_book
else ifeq ($(TOP),mii)
VERILOG_SOURCES = $(RTL)/crc32.v $(RTL)/mii_rx.v
COCOTB_TOPLEVEL = mii_rx
COCOTB_TEST_MODULES = test_mii_rx
else ifeq ($(TOP),udp)
VERILOG_SOURCES = $(RTL)/udp_strip.v
COCOTB_TOPLEVEL = udp_strip
COCOTB_TEST_MODULES = test_udp_strip
else ifeq ($(TOP),fifo)
VERILOG_SOURCES = $(RTL)/ram_sdp.v $(RTL)/sync_fifo.v
COCOTB_TOPLEVEL = sync_fifo
COCOTB_TEST_MODULES = test_sync_fifo
COMPILE_ARGS += -Psync_fifo.ADDR=$(FIFO_ADDR)
else ifeq ($(TOP),uart)
VERILOG_SOURCES = $(BOARD)/uart_tx.v $(BOARD)/uart_hello.v
COCOTB_TOPLEVEL = uart_hello
COCOTB_TEST_MODULES = test_uart_hello
COMPILE_ARGS += -Puart_hello.CLKS_PER_BIT=8 -Puart_hello.PAUSE_CLKS=200
else ifeq ($(TOP),afifo)
VERILOG_SOURCES = $(RTL)/async_fifo.v
COCOTB_TOPLEVEL = async_fifo
COCOTB_TEST_MODULES = test_async_fifo
else ifeq ($(TOP),trigger)
VERILOG_SOURCES = $(RTL)/trigger.v
COCOTB_TOPLEVEL = trigger
COCOTB_TEST_MODULES = test_trigger
else ifeq ($(TOP),miitx)
VERILOG_SOURCES = $(RTL)/crc32.v $(RTL)/async_fifo.v $(RTL)/mii_tx.v $(RTL)/order_tx.v
COCOTB_TOPLEVEL = order_tx
COCOTB_TEST_MODULES = test_mii_tx
else ifeq ($(TOP),eth)
VERILOG_SOURCES = $(ETH_SOURCES)
COCOTB_TOPLEVEL = t2t_eth_top
COCOTB_TEST_MODULES = test_eth_top
else ifeq ($(TOP),board)
VERILOG_SOURCES = $(ETH_SOURCES) $(BOARD)/uart_tx.v $(BOARD)/status_uart.v $(BOARD)/arty_t2t_top.v \
                  $(PWD)/xilinx_stubs.v
COCOTB_TOPLEVEL = arty_t2t_top
COCOTB_TEST_MODULES = test_board
COMPILE_ARGS += -Party_t2t_top.BAUD=12500000 -Party_t2t_top.STATUS_HZ=5000 -Party_t2t_top.PHY_RESET_US=20
else
VERILOG_SOURCES = $(RTL)/itch_parser.v
COCOTB_TOPLEVEL = itch_parser
COCOTB_TEST_MODULES = test_itch_parser
endif

SIM_BUILD = sim_build_$(TOP)
COCOTB_RESULTS_FILE = results_$(TOP).xml

include $(shell cocotb-config --makefiles)/Makefile.sim
