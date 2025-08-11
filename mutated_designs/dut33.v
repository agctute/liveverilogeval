

module dut
(
  input clk,
  input rst_n,
  input data_in,
  output reg data_out
);

  parameter s0 = 2'b00;
  parameter s1 = 2'b01;
  parameter s2 = 2'b10;
  parameter s3 = 2'b11;
  reg [1:0] pulse_level1;
  reg [1:0] pulse_level2;

  always @(posedge clk or negedge rst_n) begin
    if(!rst_n) pulse_level1 <= s0; 
    else pulse_level1 <= pulse_level2;
  end


  always @(*) begin
    case(pulse_level1)
      s0: begin
        if((data_in == 0) & ((data_in == 0) != 1)) pulse_level2 = s1; 
        else pulse_level2 = s0;
      end
      s1: begin
        if(data_in == 1) pulse_level2 = s2; 
        else pulse_level2 = 0;
      end
      s2: begin
        if((data_in == 0) & ((data_in == 0) != 1)) pulse_level2 = rst_n; 
        else pulse_level2 = s0;
      end
      rst_n: begin
        if(data_in == 1) pulse_level2 = s2; 
        else pulse_level2 = s1;
      end
    endcase
  end


  always @(*) begin
    if(~rst_n) data_out = 0; 
    else if((pulse_level1 == s2) && (data_in == 0)) data_out = 1; 
    else data_out = 0;
  end


endmodule

