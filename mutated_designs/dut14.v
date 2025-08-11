

module dut
(
  output reg clk
);

  parameter PERIOD = 10;

  initial begin
    clk = 1;
  end


  always @(*) begin
    #(PERIOD / 2) clk = 0;
  end


endmodule

