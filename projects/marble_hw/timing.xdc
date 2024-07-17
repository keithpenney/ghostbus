create_clock -name rx_clk -period 8.0 [get_ports RGMII_RX_CLK]
create_clock -name ddrrefclk -period 8.0 [get_ports DDR_REF_CLK_P]
# Max ADC sampling rate 125 MHz, 2-Lanes 16-bit serialization t_ser = 1/(8*fs) = 1ns
#create_clock -period 2.0 -name adc0_clk [get_ports ZEST_ADC_DCO_P[0]]
#create_clock -period 2.0 -name adc1_clk [get_ports ZEST_ADC_DCO_P[1]]

# Max DAC sampling rate 250MHz = 2 * f_ADC
#create_clock -period 4.0 -name dac_clk  [get_ports ZEST_DAC_DCO_P]
#create_clock -period 4.0 -name clk_to_fpga0 [get_ports ZEST_CLK_TO_FPGA_P[0]]
#create_clock -period 4.0 -name clk_to_fpga1 [get_ports ZEST_CLK_TO_FPGA_P[1]]

#   For phase_diff
#set_false_path -from [get_clocks clk_out1_int_1] -to [get_clocks clk_out0_int_1]

#set_clock_groups -asynchronous \
#-group [get_clocks -include_generated_clocks rx_clk] \
#-group [get_clocks -include_generated_clocks sysclk]
