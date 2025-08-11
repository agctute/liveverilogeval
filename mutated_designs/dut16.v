

module dut
(
  input [3:0] A,
  input [3:0] B,
  output A_greater,
  output A_equal,
  output A_less
);

  wire [3:0] diff;
  wire cout;
  assign { cout, diff } = 0;
  assign A_greater = ~cout && (diff != 4'b0000);
  assign A_equal = A == B;
  assign A_less = 0;

endmodule

