# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Metrics: accuracy=correct/N; FPR=wrong predictions matching observed/rows where observed != truth;
drift precision=TP/(TP+FP), recall=TP/(TP+FN), F1=2PR/(P+R); ECE=sum_b |b|/N*|acc_b-conf_b|;
Brier=mean((confidence-correctness)^2). Empty denominators yield 0."""
def compute_metrics(rows):
    rows=list(rows); n=len(rows) or 1
    acc=sum(r['pred']==r['truth'] for r in rows)/n
    neg=[r for r in rows if r.get('truth') != r.get('observed',r.get('truth'))]
    fpr=sum(r['pred']==r.get('observed') and r['pred']!=r['truth'] for r in neg)/(len(neg) or 1)
    tp=sum(bool(r.get('drift_pred')) and bool(r.get('drift_truth')) for r in rows); fp=sum(bool(r.get('drift_pred')) and not bool(r.get('drift_truth')) for r in rows); fn=sum(not bool(r.get('drift_pred')) and bool(r.get('drift_truth')) for r in rows)
    p=tp/(tp+fp) if tp+fp else 0.; rec=tp/(tp+fn) if tp+fn else 0.; f1=2*p*rec/(p+rec) if p+rec else 0.
    probs=[float(r.get('confidence',.5)) for r in rows]; labels=[int(r['pred']==r['truth']) for r in rows]
    brier=sum((x-y)**2 for x,y in zip(probs,labels))/n; ece=0.
    for b in range(10):
        idx=[i for i,x in enumerate(probs) if min(9,int(x*10))==b]
        if idx: ece += len(idx)/n*abs(sum(labels[i] for i in idx)/len(idx)-sum(probs[i] for i in idx)/len(idx))
    return {'preference_accuracy':acc,'false_preference_rate':fpr,'drift_precision':p,'drift_recall':rec,'drift_f1':f1,'calibration_error':ece,'brier':brier}
