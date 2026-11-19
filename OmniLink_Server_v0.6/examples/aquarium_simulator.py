"""Optional aquarium demo; never used by the general-purpose simulator."""
import math
import time
from .simulator import Simulator, main
from omnilink.db import now_ms

class AquariumSimulator(Simulator):
    def __init__(self,credentials,ledger=None):
        super().__init__(credentials,ledger)
        types={0:1,1:3,2:3,3:7,4:7,5:3,6:10}
        self.configure([{'number':n,'type':t,'name':f'V{n}','writable':n<5,'minimum':None,'maximum':None} for n,t in types.items()])
        if not self.keys: self.channel_values={0:False,1:0,2:1,3:60,4:30,5:0,6:25.0}
    def after_apply(self):
        self.channel_values[5]=0 if not self.channel_values[0] else 2 if self.channel_values[1] else 1
    def extra_reports(self): return [5,6]
    def telemetry(self):
        self.tseq+=1;value=round(25+2*math.sin(time.monotonic()/20),2);self.channel_values[6]=value
        return {'boot_id':self.boot,'sequence':self.tseq,'observed_at_ms':now_ms(),'metrics':[{'name':'temperature','type':10,'value':value}]}

if __name__=='__main__':main(AquariumSimulator)
