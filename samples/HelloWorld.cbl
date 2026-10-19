       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
       AUTHOR. SAKETH.
      * THIS PROGRAM DEMONSTRATES THE CST/AST PARSER
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMP-FILE ASSIGN TO "EMP.dat"
           ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
           FD EMP-FILE.
           01 EMP-RECORD.
               05 EMP-ID PIC 9(4).
               05 EMP-NAME PIC X(20).
       WORKING-STORAGE SECTION.
           01 WS-COUNTER PIC 9(3) VALUE 0.
           01 WS-NAME PIC X(20) VALUE SPACES.
           01 WS-FLAGS.
               05 WS-FLAG-A PIC X VALUE "N".
               05 WS-FLAG-B PIC X VALUE "N".
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "WORLD" TO WS-NAME.
           ADD 1 TO WS-COUNTER.
           IF WS-COUNTER > 5
               DISPLAY "BIG"
               ELSE
               DISPLAY "SMALL"
           END-IF.
           EVALUATE WS-FLAG-A
               WHEN "Y"
                   DISPLAY "FLAG A IS SET"
               WHEN OTHERS
                   DISPLAY "DEFAULT CASE"
           END-EVALUATE.
           PERFORM GREET-PARA.
           CALL "SOME-SUB" USING WS-NAME.
           STOP RUN.
       GREET-PARA.
           DISPLAY "HELLO " WS-NAME.
