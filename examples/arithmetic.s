* IBM 1401 signed decimal arithmetic demonstration
* Run: python -m ibm1401 run examples/arithmetic.s
*
* Printed lines are: sum, difference, product, quotient, remainder.
* Negative values are marked CR by Move Characters and Edit.
*
        ORG  400
START   A    ADDEND,SUM          * 0025347 + 04601231 = 04626578
        S    SUBTRAH,DIFF        * 00579 - 1000 = -421
        ZA   MPLIER,PRODUCT-5    * multiplier in high-order B-field
        M    MCAND,PRODUCT       * -1246 * 543 = -676578
        ZA   DVDEND,DIVWORK
        D    DVISOR,DIVWORK-3    * 1246 / 543 = 2 remainder 160
*
* Edit and print the sum.
        LCA  EDIT,211
        MCE  SUM,211
        W
* Edit and print the difference.
        LCA  EDIT,211
        MCE  DIFF,211
        W
* Edit and print the product.
        LCA  EDIT,211
        MCE  PRODUCT,211
        W
* The quotient is the left four digits of DIVWORK.
        LCA  EDIT,211
        MCE  DIVWORK-4,211
        W
* Delimit and print the four-digit remainder on the right.
        SW   DIVWORK-3
        LCA  EDIT,211
        MCE  DIVWORK,211
        W
        H
*
ADDEND  DCW  0025347
SUM     DCW  04601231
SUBTRAH DCW  1000
DIFF    DCW  00579
MCAND   DCW  -1246
MPLIER  DCW  543
PRODUCT DCW  00000000
DVDEND  DCW  1246
DVISOR  DCW  543
DIVWORK DCW  00000000
* Eight data positions, a blank control, and credit status.
EDIT    DCW  @00000000&CR@
        END  START
