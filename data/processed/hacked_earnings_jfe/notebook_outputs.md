# Main Analysis.ipynb — embedded notebook outputs

Source: `vgreg/hacked_earnings_jfe` at audited main commit `c23c7d79d067a79d70cf20e31b072d3703497eae`.

## Cell 0 markdown

Sample code for _Price Revelation from Insider Trading: Evidence from Hacked Earnings News_

## Cell 4 markdown

# Figure 1

## Cell 8 output

```text
<Figure size 576x360 with 2 Axes>
```

## Cell 9 markdown

# Figure 2

## Cell 14 output

```text
<Figure size 576x576 with 8 Axes>
```

## Cell 15 markdown

# Regression functions

## Cell 20 markdown

# Table 1

## Cell 21 markdown

## Panel A

## Cell 22 output

```text
Surprise $|$Surprise$|$ Ln MCAP      IO N. analysts Ln Q-value  \
Mean        0.0004          0.007   14.16   68.37        7.69       0.97   
Median      0.0006         0.0017    14.1   77.53         5.0        0.8   
Std. dev.   0.0104         0.0373    1.77   28.82        6.92       1.53   
N           43,687         43,687  43,687  43,687      43,687     35,273   

          Share turn. Option turn.  
Mean             1.99          0.2  
Median           1.46         0.04  
Std. dev.        2.11         0.47  
N              43,687       43,687
```

## Cell 23 markdown

## Panel B

Characteristic regression

## Cell 26 output

```text
Surprise $|$Surprise$|$   Ln MCAP        IO  \
                                    (1)            (2)       (3)       (4)   
$\mathbf{1}_{[\text{Hacked}]}$   -0.000          0.000  -0.195**  -3.119**   
                                (0.000)        (0.001)   (0.079)   (1.336)   
$N$                              43,687         43,687    43,687    43,687   
$R^2$                             0.000          0.000     0.002     0.001   
Year-Quarter F.E.                     Y              Y         Y         Y   
Firm F.E.                             N              N         N         N   

                               N. analysts Ln Q-value Share turn. Option turn.  
                                       (5)        (6)         (7)          (8)  
$\mathbf{1}_{[\text{Hacked}]}$      -0.153      0.045       0.051        0.003  
                                   (0.221)    (0.055)     (0.061)      (0.014)  
$N$                                 43,687     35,273      43,687       43,687  
$R^2$                                0.000      0.000       0.000        0.000  
Year-Quarter F.E.                        Y          Y           Y            Y  
Firm F.E.                                N          N           N            N
```

## Cell 27 markdown

## Panel C

Firm and year FE

## Cell 30 output

```text
Surprise $|$Surprise$|$  Ln MCAP       IO  \
                                    (1)            (2)      (3)      (4)   
$\mathbf{1}_{[\text{Hacked}]}$    0.000         -0.000    0.002    0.084   
                                (0.000)        (0.001)  (0.011)  (0.293)   
$N$                              43,687         43,687   43,687   43,687   
$R^2$                             0.000          0.000    0.000    0.000   
Year-Quarter F.E.                     Y              Y        Y        Y   
Firm F.E.                             Y              Y        Y        Y   

                               N. analysts Ln Q-value Share turn. Option turn.  
                                       (5)        (6)         (7)          (8)  
$\mathbf{1}_{[\text{Hacked}]}$       0.088     -0.021      -0.010       -0.004  
                                   (0.078)    (0.019)     (0.032)      (0.006)  
$N$                                 43,687     35,273      43,687       43,687  
$R^2$                                0.000      0.000       0.000        0.000  
Year-Quarter F.E.                        Y          Y           Y            Y  
Firm F.E.                                Y          Y           Y            Y
```

## Cell 31 markdown

# Table 2

## Cell 32 markdown

## Panel A

Heatmap

## Cell 34 output

```text
<Figure size 432x288 with 1 Axes>
```

## Cell 35 markdown

## Panel B

## Cell 37 output

```text
(1)        (2)        (3)
$Surprise$   1.313***        NaN   1.184***
              (0.048)        NaN    (0.051)
$Soft$            NaN   1.201***   1.047***
                  NaN    (0.036)    (0.035)
Intercept   -0.002***  -0.002***  -0.003***
              (0.000)    (0.000)    (0.000)
$N$            43,687     36,750     36,750
$R^2$           0.061      0.068      0.115
```

## Cell 38 markdown

# Table 3

## Cell 39 markdown

## Panel A

## Cell 42 output

```text
(1)       (2)       (3)  \
$Surprise$                                    1.364***  1.436***  1.443***   
                                               (0.073)   (0.079)   (0.079)   
$Surprise\times\mathbf{1}_{[\text{Hacked}]}$  -0.212**  -0.234**  -0.241**   
                                               (0.103)   (0.103)   (0.104)   
$\mathbf{1}_{[\text{Hacked}]}$                  -0.001    -0.001    -0.001   
                                               (0.001)   (0.001)   (0.001)   
$N$                                             43,687    43,687    43,687   
$R^2$                                            0.062     0.060     0.071   
Controls                                             N         N         Y   
Year-Quarter F.E.                                    Y         Y         Y   
Firm F.E.                                            N         Y         Y   
Date F.E.                                            N         N         N   

                                                   (4)  
$Surprise$                                    1.426***  
                                               (0.062)  
$Surprise\times\mathbf{1}_{[\text{Hacked}]}$  -0.215**  
                                               (0.101)  
$\mathbf{1}_{[\text{Hacked}]}$                  -0.000  
                                               (0.001)  
$N$                                             43,687  
$R^2$                                            0.067  
Controls                                             Y  
Year-Quarter F.E.                                    N  
Firm F.E.                                            Y  
Date F.E.                                            Y
```

## Cell 43 markdown

## Panel B

## Cell 45 output

```text
(1)       (2)       (3)  \
$Soft$                                    1.246***  1.352***  1.345***   
                                           (0.062)   (0.065)   (0.063)   
$Soft\times\mathbf{1}_{[\text{Hacked}]}$   -0.184*  -0.220**  -0.222**   
                                           (0.097)   (0.099)   (0.100)   
$\mathbf{1}_{[\text{Hacked}]}$              -0.001    -0.001    -0.001   
                                           (0.001)   (0.001)   (0.001)   
$N$                                         36,750    36,750    36,750   
$R^2$                                        0.069     0.062     0.072   
Controls                                         N         N         Y   
Year-Quarter F.E.                                Y         Y         Y   
Firm F.E.                                        N         Y         Y   
Date F.E.                                        N         N         N   

                                               (4)  
$Soft$                                    1.334***  
                                           (0.045)  
$Soft\times\mathbf{1}_{[\text{Hacked}]}$  -0.210**  
                                           (0.083)  
$\mathbf{1}_{[\text{Hacked}]}$              -0.001  
                                           (0.001)  
$N$                                         36,750  
$R^2$                                        0.068  
Controls                                         Y  
Year-Quarter F.E.                                N  
Firm F.E.                                        Y  
Date F.E.                                        Y
```

## Cell 46 markdown

## Panel C

## Cell 47 output

```text
(1)       (2)       (3)  \
$Surprise$                                    1.225***  1.326***  1.336***   
                                               (0.071)   (0.081)   (0.081)   
$Soft$                                        1.090***  1.192***  1.183***   
                                               (0.060)   (0.060)   (0.059)   
$Surprise\times\mathbf{1}_{[\text{Hacked}]}$    -0.174   -0.199*   -0.207*   
                                               (0.111)   (0.111)   (0.112)   
$Soft\times\mathbf{1}_{[\text{Hacked}]}$      -0.179**  -0.202**  -0.202**   
                                               (0.088)   (0.091)   (0.092)   
$\mathbf{1}_{[\text{Hacked}]}$                  -0.001    -0.001    -0.001   
                                               (0.001)   (0.001)   (0.001)   
$N$                                             36,750    36,750    36,750   
$R^2$                                            0.115     0.110     0.120   
Controls                                             N         N         Y   
Year-Quarter F.E.                                    Y         Y         Y   
Firm F.E.                                            N         Y         Y   
Date F.E.                                            N         N         N   

                                                   (4)  
$Surprise$                                    1.308***  
                                               (0.064)  
$Soft$                                        1.176***  
                                               (0.042)  
$Surprise\times\mathbf{1}_{[\text{Hacked}]}$    -0.144  
                                               (0.113)  
$Soft\times\mathbf{1}_{[\text{Hacked}]}$      -0.193**  
                                               (0.080)  
$\mathbf{1}_{[\text{Hacked}]}$                  -0.001  
                                               (0.001)  
$N$                                             36,750  
$R^2$                                            0.116  
Controls                                             Y  
Year-Quarter F.E.                                    N  
Firm F.E.                                            Y  
Date F.E.                                            Y
```

## Cell 48 markdown

# Table 4

## Cell 50 output

```text
Dependant variable return window  \
                                                          12 p.m.(t)-9:30 a.m.(t+1)   
                                                                                (1)   
$Return^{12-4PM}$                                                          0.776***   
                                                                            (0.029)   
$Return^{12-4PM}\times\mathbf{1}_{[\text{Hacked...                         0.130***   
                                                                            (0.044)   
$\mathbf{1}_{[\text{Hacked}]}$                                               -0.001   
                                                                            (0.001)   
$N$                                                                          43,687   
$R^2$                                                                         0.082   
Controls                                                                          Y   
Year-Quarter F.E.                                                                 Y   
Firm F.E.                                                                         Y   

                                                                           
                                                   12 p.m.(t)-4 p.m.(t+1)  
                                                                      (2)  
$Return^{12-4PM}$                                                0.591***  
                                                                  (0.038)  
$Return^{12-4PM}\times\mathbf{1}_{[\text{Hacked...                0.142**  
                                                                  (0.059)  
$\mathbf{1}_{[\text{Hacked}]}$                                     -0.001  
                                                                  (0.001)  
$N$                                                                43,687  
$R^2$                                                               0.057  
Controls                                                                Y  
Year-Quarter F.E.                                                       Y  
Firm F.E.                                                               Y
```

## Cell 51 markdown

## Table 5

## Cell 54 markdown

## Panel A

## Cell 56 output

```text
High $|\text{soft}|$            \
                                                              (1)       (2)   
$Surprise$                                               1.759***  1.763***   
                                                          (0.119)   (0.119)   
$Surprise\times\mathbf{1}_{[\text{Hacked}]}$             -0.334**  -0.329**   
                                                          (0.164)   (0.162)   
$\mathbf{1}_{[\text{Hacked}]}$                             -0.001    -0.001   
                                                          (0.002)   (0.001)   
$N$                                                        18,375    18,375   
$R^2$                                                       0.076     0.087   
Controls                                                        N         Y   
Year-Quarter F.E.                                               Y         Y   
Firm F.E.                                                       Y         Y   

                                             Low $|\text{soft}|$            
                                                             (3)       (4)  
$Surprise$                                              1.291***  1.314***  
                                                         (0.108)   (0.107)  
$Surprise\times\mathbf{1}_{[\text{Hacked}]}$              -0.215    -0.245  
                                                         (0.150)   (0.153)  
$\mathbf{1}_{[\text{Hacked}]}$                            -0.001    -0.001  
                                                         (0.001)   (0.001)  
$N$                                                       18,375    18,375  
$R^2$                                                      0.048     0.061  
Controls                                                       N         Y  
Year-Quarter F.E.                                              Y         Y  
Firm F.E.                                                      Y         Y
```

## Cell 57 markdown

## Panel B

## Cell 59 output

```text
High $|\text{surprise}|$            \
                                                              (1)       (2)   
$Soft$                                                   1.638***  1.630***   
                                                          (0.091)   (0.090)   
$Soft\times\mathbf{1}_{[\text{Hacked}]}$                 -0.336**  -0.333**   
                                                          (0.131)   (0.131)   
$\mathbf{1}_{[\text{Hacked}]}$                             -0.001    -0.001   
                                                          (0.002)   (0.002)   
$N$                                                        18,375    18,375   
$R^2$                                                       0.079     0.084   
Controls                                                        N         Y   
Year-Quarter F.E.                                               Y         Y   
Firm F.E.                                                       Y         Y   

                                         Low $|\text{surprise}|$            
                                                             (3)       (4)  
$Soft$                                                  0.934***  0.925***  
                                                         (0.058)   (0.058)  
$Soft\times\mathbf{1}_{[\text{Hacked}]}$                  -0.126    -0.134  
                                                         (0.122)   (0.123)  
$\mathbf{1}_{[\text{Hacked}]}$                             0.000     0.000  
                                                         (0.001)   (0.001)  
$N$                                                       18,375    18,375  
$R^2$                                                      0.037     0.064  
Controls                                                       N         Y  
Year-Quarter F.E.                                              Y         Y  
Firm F.E.                                                      Y         Y
```

## Cell 60 markdown

# Figure 4

## Cell 64 markdown

## Panel A

## Cell 65 output

```text
<Figure size 432x288 with 1 Axes>
```

## Cell 66 markdown

## Panel B

## Cell 69 output

```text
<Figure size 432x288 with 1 Axes>
```

## Cell 70 markdown

## Panel C

## Cell 73 output

```text
<Figure size 432x288 with 1 Axes>
```

## Cell 74 markdown

## Panel D

## Cell 77 output

```text
<Figure size 432x288 with 1 Axes>
```



---

# Insider Trading Measures.ipynb — embedded notebook outputs

Source: `vgreg/hacked_earnings_jfe` at audited main commit `c23c7d79d067a79d70cf20e31b072d3703497eae`.

## Cell 0 markdown

Sample code to generate Table 6

## Cell 3 markdown

# Regression: Hacked vs non-hacked

## Cell 7 markdown

## Table 5

## Cell 8 markdown

## Panel A

## Cell 10 output

```text
Order flow measures                 \
                                        Share turn Log(share vol)   
                                               (1)            (2)   
$\mathbf{1}_{[\text{Hacked}]}$           0.0490***       0.0350**   
                                            (0.02)         (0.01)   
$N$                                         43,687         43,687   
$R^2$                                        0.021          0.038   
Controls                                         Y              Y   
Year-Quarter F.E.                                Y              Y   
Firm F.E.                                        Y              Y   

                                                             Spread measures  \
                               \big|OI\big| Log(option vol) Effective spread   
                                        (3)             (4)              (5)   
$\mathbf{1}_{[\text{Hacked}]}$       0.0080        0.0721**        0.0312***   
                                     (0.01)          (0.03)           (0.01)   
$N$                                  43,687          43,687           43,687   
$R^2$                                 0.013           0.054            0.153   
Controls                                  Y               Y                Y   
Year-Quarter F.E.                         Y               Y                Y   
Firm F.E.                                 Y               Y                Y   

                                                                           
                               Realized spread Price impact Quoted spread  
                                           (6)          (7)           (8)  
$\mathbf{1}_{[\text{Hacked}]}$       0.0445***       0.0153       -0.0140  
                                        (0.02)       (0.01)        (0.02)  
$N$                                     43,687       43,687        43,687  
$R^2$                                    0.034        0.128         0.022  
Controls                                     Y            Y             Y  
Year-Quarter F.E.                            Y            Y             Y  
Firm F.E.                                    Y            Y             Y
```

## Cell 11 markdown

## Panel B

## Cell 13 output

```text
Order flow measures                 \
                                        Share turn Log(share vol)   
                                               (1)            (2)   
$\mathbf{1}_{[\text{Hacked}]}$             -0.0092        -0.0176   
                                            (0.01)         (0.02)   
$N$                                         43,687         43,687   
$R^2$                                        0.017          0.033   
Controls                                         Y              Y   
Year-Quarter F.E.                                Y              Y   
Firm F.E.                                        Y              Y   

                                                             Spread measures  \
                               \big|OI\big| Log(option vol) Effective spread   
                                        (3)             (4)              (5)   
$\mathbf{1}_{[\text{Hacked}]}$      -0.0099          0.0331           0.0063   
                                     (0.01)          (0.03)           (0.01)   
$N$                                  43,687          43,687           43,687   
$R^2$                                 0.011           0.046            0.100   
Controls                                  Y               Y                Y   
Year-Quarter F.E.                         Y               Y                Y   
Firm F.E.                                 Y               Y                Y   

                                                                           
                               Realized spread Price impact Quoted spread  
                                           (6)          (7)           (8)  
$\mathbf{1}_{[\text{Hacked}]}$          0.0127      -0.0137       0.0178*  
                                        (0.01)       (0.01)        (0.01)  
$N$                                     43,687       43,687        43,687  
$R^2$                                    0.030        0.024         0.101  
Controls                                     Y            Y             Y  
Year-Quarter F.E.                            Y            Y             Y  
Firm F.E.                                    Y            Y             Y
```

## Cell 14 markdown

## Panel C

## Cell 17 output

```text
Order flow measures                           \
                             Turnover Log(volume) \big|OI\big|   
                                  (1)         (2)          (3)   
Difference                     0.0582      0.0526       0.0179   
P-value                        0.0049      0.0123       0.3537   

                                   Spread measures                  \
                  Log(option vol) Effective spread Realized spread   
                              (4)              (5)             (6)   
Difference                 0.0390           0.0249          0.0318   
P-value                    0.3533           0.1201          0.1594   

                                              
                  Price impact Quoted spread  
                           (7)           (8)  
Difference             -0.0003       -0.0026  
P-value                 0.9915        0.8545
```



---

# Wordcloud.ipynb — embedded notebook outputs

Source: `vgreg/hacked_earnings_jfe` at audited main commit `c23c7d79d067a79d70cf20e31b072d3703497eae`.

## Cell 0 markdown

Notebook to generate the word clouds, requires `wordcloud` module. Note that this module uses the random number generator, so each pass generates a new word cloud (with the same words).

## Cell 4 output

```text
word      coef
604   disappoint -0.027961
558        delay -0.006116
1012       howev -0.004983
338     challeng -0.004463
1978      slower -0.003200
...          ...       ...
1598       pleas  0.002737
1369    momentum  0.003291
755         exce  0.003359
756       exceed  0.004010
1709        rais  0.006816

[2393 rows x 2 columns]
```

## Cell 5 output

```text
2393
```

## Cell 10 output

```text
<Figure size 1152x864 with 1 Axes>
```

## Cell 11 output

```text
<Figure size 1152x864 with 1 Axes>
```

