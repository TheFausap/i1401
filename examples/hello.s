* Read one card, print it, and punch a copy.
* Run: python -m ibm1401 run examples/hello.s --cards examples/cards.txt
*
* Keep the program above the reader (001-080), punch (101-180), and
* printer (201-332) areas.
        ORG  400
START   SW   1,201               * delimit input and print fields
        SW   101                 * delimit punch field
        R
        MCW  80,180              * card reader to punch area
        MCW  80,280              * card reader to print area
        W
        P
        H
        END  START
