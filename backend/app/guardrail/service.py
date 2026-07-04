import re
SENSITIVE=[r'password\s*[:=]',r'token\s*[:=]',r'secret\s*[:=]',r'\b\d{11}\b',r'\b\d{17}[0-9Xx]\b']
DANGER=[r'rm\s+-rf',r'chmod\s+777',r'/etc/passwd',r'/root/']
def evaluate(text:str)->dict:
    risk=0; hits=[]
    for p in SENSITIVE:
        if re.search(p,text,re.I): risk+=2; hits.append(p)
    for p in DANGER:
        if re.search(p,text,re.I): risk+=3; hits.append(p)
    level='S0' if risk==0 else ('S1' if risk<=2 else ('S2' if risk<=4 else 'S3'))
    return {'risk':risk,'hits':hits,'sensitivity_level':level,'trust_score':max(0.0,1.0-risk*0.18)}
