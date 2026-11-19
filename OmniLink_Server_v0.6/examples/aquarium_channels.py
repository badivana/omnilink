"""Optional example schema, outside the general-purpose server."""
AQUARIUM_CHANNELS=[
    {'number':0,'name':'Master power','type':1,'writable':True},
    {'number':1,'name':'FILTER 0 / AIR 1','type':3,'writable':True,'minimum':0,'maximum':1},
    {'number':2,'name':'AUTO 0 / MANUAL 1','type':3,'writable':True,'minimum':0,'maximum':1},
    {'number':3,'name':'Filter duration seconds','type':7,'writable':True,'minimum':1,'maximum':86400},
    {'number':4,'name':'Air duration seconds','type':7,'writable':True,'minimum':1,'maximum':86400},
    {'number':5,'name':'Actual OFF 0 / FILTER 1 / AIR 2','type':3,'writable':False,'minimum':0,'maximum':2},
    {'number':6,'name':'Water temperature','type':10,'writable':False,'minimum':-50,'maximum':100},
]
