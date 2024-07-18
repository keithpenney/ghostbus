// Simple Top-level module targetting the Marble platform
// Copied and simplified from:
//   bedrock/projects/test_marble_family/marble_top.v
//   uspas_llrf/udp_rgmii/udp_rgmii_expand.v

module marble_top(
  input DDR_REF_CLK_P,
  input DDR_REF_CLK_N,

  // RGMII Tx port
  output [3:0] RGMII_TXD,
  output RGMII_TX_CTRL,
  output RGMII_TX_CLK,

  // RGMII Rx port
  input [3:0] RGMII_RXD,
  input RGMII_RX_CTRL,
  input RGMII_RX_CLK,

  // Reset command to PHY
  output PHY_RSTN,

  // SPI pins connected to microcontroller
  input SCLK,
  input CSB,
  input MOSI,
  output MISO,
  //output MMC_INT,

  // UART to USB
  // The RxD and TxD directions are with respect
  // to the USB/UART chip, not the FPGA!
  //output FPGA_RxD,
  //input FPGA_TxD,

  output VCXO_EN,

  // output ZEST_PWR_EN,

  // Directly attached LEDs
  output LD16,
  output LD17,

  // Physical Pmod, may be used as LEDs
  output [7:0] Pmod1   // feel free to change to inout, if you attach to something other than LEDs
  //input [7:0] Pmod2
);

assign PHY_RSTN = 1'b1;

wire ddrrefclk_unbuf, ddrrefclk;
IBUFDS ddri_125(.I(DDR_REF_CLK_P), .IB(DDR_REF_CLK_N), .O(ddrrefclk_unbuf));
// Vivado fails, with egregiously useless error messages,
// if you don't put this BUFG in the chain to the MMCM.
BUFG ddrg_125(.I(ddrrefclk_unbuf), .O(ddrrefclk));

parameter in_phase_tx_clk = 1;
// Standardized interface, hardware-dependent implementation
wire tx_clk90;
wire clk_locked;
wire pll_reset = 0;  // or RESET?
wire gmii_tx_clk;
wire clk_out1;
wire clk200;  // clk200 should be 200MHz +/- 10MHz or 300MHz +/- 10MHz,
// used for calibrating IODELAY cells

// You really want to set this define.
// It's only valid to leave it off when C_USE_RGMII_IDELAY is 0.
// It might be useful to not define it if you're exploring parameter space
// or have problems with the Xilinx DNA readout.
`define USE_IDELAYCTRL

wire clk125 = ddrrefclk;

xilinx7_clocks #(
  .DIFF_CLKIN("BYPASS"),
  .CLKIN_PERIOD(8),  // REFCLK = 125 MHz
  .MULT     (8),     // 125 MHz X 8 = 1 GHz on-chip VCO
  .DIV0     (8),     // 1 GHz / 8 = 125 MHz
`ifdef USE_IDELAYCTRL
  .DIV1     (5)     // 1 GHz / 5 = 200 MHz
`else
  .DIV1     (16)     // 1 GHz / 16 = 62.5 MHz
`endif
) clocks_i(
  .sysclk_p (clk125),
  .sysclk_n (1'b0),
  .reset    (pll_reset),
  .clk_out0 (gmii_tx_clk), // output
  .clk_out1 (clk_out1), // output
  .clk_out2 (tx_clk90), // output
  .clk_out3f(),  // output not buffered, straight from MMCM
  .locked   (clk_locked)
);

`ifdef USE_IDELAYCTRL
assign clk200 = clk_out1;
reg bad_slow_clock=0;
always @(posedge gmii_tx_clk) bad_slow_clock <= ~bad_slow_clock;
`else
assign clk200 = 0;
`endif

// Double-data-rate conversion
wire vgmii_rx_clk;
wire [7:0] vgmii_txd, vgmii_rxd;
wire vgmii_tx_en, vgmii_tx_er, vgmii_rx_dv, vgmii_rx_er;
gmii_to_rgmii #(
  .use_idelay(0),
  .in_phase_tx_clk(in_phase_tx_clk)
) gmii_to_rgmii_i(
  .rgmii_txd(RGMII_TXD), // output [3:0]
  .rgmii_tx_ctl(RGMII_TX_CTRL), // output
  .rgmii_tx_clk(RGMII_TX_CLK), // output
  .rgmii_rxd(RGMII_RXD), // input [3:0]
  .rgmii_rx_ctl(RGMII_RX_CTRL), // input
  .rgmii_rx_clk(RGMII_RX_CLK), // input

  .gmii_tx_clk(gmii_tx_clk), // input
  .gmii_tx_clk90(tx_clk90), // input
  .gmii_txd(vgmii_txd), // input [7:0]
  .gmii_tx_en(vgmii_tx_en), // input
  .gmii_tx_er(vgmii_tx_er), // input
  .gmii_rxd(vgmii_rxd), // output [7:0]
  .gmii_rx_clk(vgmii_rx_clk), // output
  .gmii_rx_dv(vgmii_rx_dv), // output
  .gmii_rx_er(vgmii_rx_er), // output

  .clk_div(1'b0), // input
  .idelay_ce(1'b0), // input
  .idelay_value_in(5'h00), // input [4:0]
  .idelay_value_out_ctl(), // output [4:0]
  .idelay_value_out_data() // output [4:0]
);

// Basic clock setup
wire tx_clk = gmii_tx_clk;
wire rx_clk = vgmii_rx_clk;

// ============================== Ghostbus ===========================
// LB controller <============ This is the Ghostbus!
localparam GB_AW = 24;
localparam GB_DW = 32;
(* ghostbus_port="clk" *) wire lb_clk = gmii_tx_clk;
(* ghostbus_port="addr" *) wire [GB_AW-1:0] lb_addr;
(* ghostbus_port="wen" *) wire lb_write;
//(* ghostbus_port="ren" *) wire lb_read;
(* ghostbus_port="wdata" *) wire [GB_DW-1:0] lb_wdata;
(* ghostbus_port="rdata" *) wire [GB_DW-1:0] lb_rdata;
(* ghostbus_port="rstb" *) wire lb_rvalid;

// ============================== Mailbox =============================
// The MMC mailbox is an external ghostbus module
(* ghostbus_ext="spi_mbox, addr" *) wire [10:0] mailbox_addr;
(* ghostbus_ext="spi_mbox, wdata" *) wire [7:0]  mailbox_wdata;
(* ghostbus_ext="spi_mbox, rdata" *) wire [7:0]  mailbox_rdata;
(* ghostbus_ext="spi_mbox, wen" *) wire mailbox_wen;
//(* ghostbus_ext="spi_mbox, ren" *) wire mailbox_ren;

// This control strobe is required for the mailbox interface but is
// not a standard "localbus" port according to ghostbus, so it's
// tagging along as an "extra output".
(* ghostbus_ext="spi_mbox, extra_out0" *) wire mailbox_ctrl_strobe;

`ifndef LB_GATEWAY_TEST
(* ghostbus_port="extra_out0" *) wire lb_control_strobe;
wire lb_control_rd, lb_control_rd_valid;
assign lb_write  = lb_control_strobe & ~lb_control_rd;
assign lb_rvalid = lb_control_rd_valid;
//assign lb_read   = |control_pipe_rd;
`else
(* ghostbus_port="extra_out0" *) wire lb_pre_rvalid;
`endif

// Signals provided by mmc_mailbox
wire enable_rx;
wire [7:0] mbox_out2;
wire config_s, config_p;
wire [7:0] config_a, config_d;

localparam default_enable_rx = 1;
// Actual mmc_mailbox instance
mmc_mailbox #(
  .DEFAULT_ENABLE_RX(default_enable_rx)
  ) spi_mbox (
  .clk(gmii_tx_clk), // input
  // localbus
  .lb_addr(mailbox_addr), // input [10:0]
  .lb_din(mailbox_wdata), // input [7:0]
  .lb_dout(mailbox_rdata), // output [7:0]
  .lb_write(mailbox_wen), // input
  .lb_control_strobe(mailbox_ctrl_strobe), // input
  // SPI PHY
  .sck(SCLK), // input
  .ncs(CSB), // input
  .pico(MOSI), // input
  .poci(MISO), // output
  // Config pins for badger (rtefi) interface
  .config_s(config_s), // output
  .config_p(config_p), // output
  .config_a(config_a), // output [7:0]
  .config_d(config_d), // output [7:0]
  // Special pins
  .enable_rx(enable_rx), // output
  .spi_pins_debug() // {MISO, din, sclk_d1, csb_d1};
);

// ============================= Badger ==========================
localparam [31:0] IP = {8'd192, 8'd168, 8'd19, 8'd10};  // 192.168.19.10
localparam [47:0] MAC = 48'h12555500032d;
localparam enable_bursts=1;
wire allow_mmc_eth_config = 1'b0; // TODO - changeme
// Be careful with clock domains:
// rtefi_blob uses this in rx_clk, so send it a registered value.
reg enable_rx_r=0;  always @(posedge gmii_tx_clk) enable_rx_r <= enable_rx | ~allow_mmc_eth_config;

localparam LB_READ_DELAY = 3;
wire rx_mon, tx_mon;
rtefi_blob #(
    .ip(IP), .mac(MAC), .p2_read_pipe_len(LB_READ_DELAY)
) badger (
    .tx_clk         (tx_clk), // input
    .rx_clk         (rx_clk), // input
    .rxd            (vgmii_rxd), // input [7:0]
    .rx_dv          (vgmii_rx_dv), // input
    .rx_er          (vgmii_rx_er), // input
    .txd            (vgmii_txd), // output [7:0]
    .tx_en          (vgmii_tx_en), // output
    .tx_er          (vgmii_tx_er), // output

    .enable_rx      (enable_rx_r), // input
    .config_clk     (tx_clk), // input
    .config_a       (config_a[3:0]),  // input [3:0]
    .config_d       (config_d),  // input [7:0]
    .config_s       (config_s & allow_mmc_eth_config),  // input MAC/IP address write
    .config_p       (config_p & allow_mmc_eth_config),  // input UDP port number write

    .host_raddr     (),
    .host_rdata     (16'h0),
    .buf_start_addr (10'h0),
    .tx_mac_start   (1'b0),
    .rx_mac_hbank   (1'b0),
    .rx_mac_accept  (1'b0),
    .tx_mac_done    (),

`ifdef LB_GATEWAY_TEST
    .p2_lb_clk      (),
    .p2_lb_addr     (lb_addr),
    .p2_lb_write    (lb_write),
    .p2_lb_read     (lb_read),
    .p2_lb_rvalid   (lb_rvalid),
    .p2_lb_wdata    (lb_wdata),
    //.p2_lb_pre_rvalid(lb_pre_rvalid),
    .p2_lb_rdata    (lb_rdata),
`else
    .p2_addr        (lb_addr),
    .p2_control_strobe(lb_control_strobe),
    .p2_control_rd  (lb_control_rd),
    .p2_control_rd_valid(lb_control_rd_valid),
    .p2_data_out    (lb_wdata),
    .p2_data_in     (lb_rdata),
`endif

    .rx_mon         (rx_mon), // output
    .tx_mon         (tx_mon) // output
);
//assign in_use = blob_in_use | boot_busy;
wire clk = tx_clk;

(* ghostbus_ext="rom, rdata" *) wire [15:0] romx_rdata;
(* ghostbus_ext="rom, addr", ghostbus_addr='h4000 *) wire [10:0] romx_addr;
// Prevent recursive dependency
`ifndef YOSYS
// Configuration ROM
config_romx rom (
    .clk(clk), .address(romx_addr), .data(romx_rdata)
);
`endif

wire [7:0] leds;
assign Pmod1 = leds;
assign LD16 = leds[0];
assign LD17 = leds[1];

assign VCXO_EN = 1'b0;

// A few test registers to read/write
(* ghostbus *) reg [7:0]  test_reg_0=8'hcc;        // Host-accessible register (will be auto-decoded)
(* ghostbus *) reg [31:0] test_reg_1=32'hceceface; // Host-accessible register (will be auto-decoded)

`ifdef GHOSTBUS_LIVE
  initial $display("Going live with ghostbus!");
  `include "defs.vh"
  `GHOSTBUS_marble_top
`endif

endmodule
