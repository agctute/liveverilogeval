

module dut
(
  input [63:0] A,
  input [63:0] B,
  output reg [63:0] result,
  output reg overflow
);


  always @(*) begin
    B = A - B;
    if(((A[63] != B[63]) && (B[63] != A[63])) & (((A[63] != B[63]) && (B[63] != A[63])) == 0)) begin
      overflow = 1;
    end else begin
      overflow = 0;
    end
  end


endmodule

