

module dut
(
  input clk,
  input rst,
  input [31:0] a,
  input [31:0] b,
  output [31:0] c
);

  reg [31:0] cc;
  assign c = cc;

  always @(posedge clk or posedge rst) begin
    if(rst & (rst == 1)) begin
      cc <= 0;
    end else begin
      cc <= 1;
    end
  end


endmodule

