from __future__ import annotations
import io, json, urllib.request, zipfile
from datetime import datetime

ARCHIVES={
  2013:"https://raw.githubusercontent.com/vgreg/hacked_earnings_jfe/main/Data/Press%20releases/2013.zip",
  2015:"https://raw.githubusercontent.com/vgreg/hacked_earnings_jfe/main/Data/Press%20releases/2015.zip",
}
KNOWN={
  2013:{
    "2013/QTR2/91498_20130425_0.txt":"2013-04-25T20:15:00Z",
    "2013/QTR2/81162_20130425_0.txt":"2013-04-25T20:01:00Z",
    "2013/QTR2/79507_20130425_0.txt":"2013-04-25T20:05:00Z",
    "2013/QTR3/86979_20130723_0.txt":"2013-07-23T20:05:00Z",
    "2013/QTR4/61241_20131017_0.txt":"2013-10-17T20:15:00Z",
  },
  2015:{
    "2015/QTR1/85663_20150121_0.txt":"2015-01-21T21:10:00Z",
    "2015/QTR1/13110_20150319_0.txt":"2015-03-19T20:01:00Z",
    "2015/QTR1/35051_20150224_0.txt":"2015-02-24T12:00:00Z",
    "2015/QTR1/75654_20150212_0.txt":None,
    "2015/QTR2/12449_20150430_0.txt":"2015-04-30T20:01:00Z",
  }
}
out={}
for year,url in ARCHIVES.items():
  req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
  data=urllib.request.urlopen(req,timeout=60).read()
  z=zipfile.ZipFile(io.BytesIO(data))
  names=set(z.namelist())
  rows=[]
  for target,exact in KNOWN[year].items():
    candidates=[n for n in names if n.endswith(target.split("/",1)[1])]
    if not candidates:
      rows.append({"target":target,"found":False,"exact":exact});continue
    n=sorted(candidates)[0]; info=z.getinfo(n)
    rows.append({
      "target":target,"found":True,"actual_name":n,
      "zip_datetime":"%04d-%02d-%02dT%02d:%02d:%02d"%info.date_time,
      "exact":exact,
      "compress_type":info.compress_type,
      "file_size":info.file_size,
    })
  from collections import Counter
  counts=Counter(info.date_time for info in z.infolist())
  out[str(year)]={"entries":len(z.infolist()),"distinct_zip_datetimes":len(counts),"most_common":[[list(k),v] for k,v in counts.most_common(5)],"known":rows}
print(json.dumps(out,indent=2))
