/*
  G2 WRDS TAQ millisecond extractor.
  Adapted from gen-li/Extract_TAQ_from_WRDS_Cloud.
  Input CSV columns: smbl,dates where dates is YYYYMMDD.
  record_type must be ctm (trades) or cqm (quotes).
*/

/* FAIL-CLOSED ACCESS CONTRACT:
   Run only inside a WRDS environment under the operator's own current
   institution/entity authorization with applicable TAQ entitlement.
   This repository does not establish personal WRDS access or data rights.
*/
%let g2_wrds_authorized=%sysget(G2_WRDS_AUTHORIZED);
%if %upcase(%superq(g2_wrds_authorized)) ne YES %then %do;
  %put ERROR: G2 WRDS extraction disabled. Set G2_WRDS_AUTHORIZED=YES only after current institutional/entity WRDS and TAQ entitlement are verified.;
  %abort cancel;
%end;

%let input_file=
%let output_file=;
%let record_type=ctm;

data g2_pairs;
  infile "&input_file" dlm="," dsd firstobs=2 truncover;
  length smbl $32 dates_text $8;
  input smbl $ dates_text $;
  dates=input(dates_text,yymmdd8.);
  format dates yymmdd10.;
run;

proc sql noprint;
  select distinct dates into :g2_dates separated by ' '
  from g2_pairs
  order by dates;
quit;

%macro g2_msec_list(type=);
  %let i=1;
  %let d=%scan(&g2_dates,&i);
  %do %while(%length(&d));
    %let yyyymmdd=%sysfunc(putn(&d,yymmddn8.));
    %if %sysfunc(exist(taqmsec.&type._&yyyymmdd)) %then taqmsec.&type._&yyyymmdd;
    %let i=%eval(&i+1);
    %let d=%scan(&g2_dates,&i);
  %end;
%mend;

data g2_raw;
  set %g2_msec_list(type=&record_type) open=defer;
run;

proc sql;
  create table g2_output as
  select b.*
  from g2_raw b
  inner join g2_pairs a
    on upcase(a.smbl)=upcase(b.sym_root)
   and a.dates=b.date;
quit;

proc export data=g2_output outfile="&output_file" dbms=csv replace;
run;
