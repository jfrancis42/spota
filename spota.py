#!/usr/bin/env python3
# coding: utf-8

# TODO: Fix band calculations for non-USA. Maybe do W=c/F and round?
# TODO: Deal with center_own state properly in Three/show().
# TODO: Add the rest of the gone_freq list.
# TODO: Clean up the whole mobile bands thing.
# TODO: Read setup from a file.
# TODO: Add command line options for debug, etc.
# TODO: Display the newest spot when there's a hash collision (ie, more than one).
# TODO: Tune to the newest spot when there's a hash collision (ie, more than one).

import sys
import os
import curses
import socket
import json
import time
import array
import datetime
import threading
import mmh3
from threading import Thread
import requests
import urllib3
urllib3.disable_warnings()
from dateutil.parser import parse
import argparse
import Hamlib

global spots_lock
global spots
global updating
global s
global sel_bands
global sel_modes
global refresh
global max_age
global rig
global logfile
global worked
global unheard
global heard
global allspots
global debug

debug=False
spots=array.array('i',[])
allspots=[]
worked=[]
unheard=[]
heard=[]
updating=False
spots_lock=threading.Lock()
s=False
refresh=60
max_age=600

def log(stuff):
  global logfile
  logfile.write(str(datetime.datetime.now())+':'+stuff+'\n')
  logfile.flush()

# Note that this assumes US bandplan.
def band(freq):
  if(freq>=3500000 and freq<=4000000):
    return('eighty')
  elif(freq>=5330000 and freq<=5410000):
    return('sixty')
  elif(freq>=7000000 and freq<=7300000):
    return('forty')
  elif(freq>=10100000 and freq<=10150000):
    return('thirty')
  elif(freq>=14000000 and freq<=14350000):
    return('twenty')
  elif(freq>=18068000 and freq<=18168000):
    return('seventeen')
  elif(freq>=21000000 and freq<=21450000):
    return('fifteen')
  elif(freq>=24890000 and freq<=24990000):
    return('twelve')
  elif(freq>=28000000 and freq<=29700000):
    return('ten')
  else:
    return('unknown')

def clean_call(call):
  return(sorted(call.split('/'),key=lambda c: len(c),reverse=True)[0])

# two-way switch
class Two:
  def __init__(self,left_name,right_name,
               left_value,right_value,
               default):
    self.left_name=left_name
    self.right_name=right_name
    self.left_value=left_value
    self.right_value=right_value
    self.default=default
    self.state=default

  def get_value(self):
    if(self.state=='l'):
      return([self.left_value])
    elif(self.state=='r'):
      return([self.right_value])

  def set_state(self,new):
    if(new=='l' or
       new=='r'):
      self.state=new
    else:
      self.state=self.default

  def toggle(self):
    if(self.state=='l'):
      self.state='r'
    elif(self.state=='r'):
      self.state='l'
    else:
      self.state=self.default

  def show(self):
    if(self.state=='l'):
      return(self.left_name+' (*) ( ) '+self.right_name)
    elif(self.state=='r'):
      return(self.left_name+' ( ) (*) '+self.right_name)

# three-way switch
class Three:
  def __init__(self,left_name,center_name,right_name,
               left_value,center_value,right_value,
               center_both,center_neither,center_own,
               default):
    self.left_name=left_name
    self.center_name=center_name
    self.right_name=right_name
    self.left_value=left_value
    self.center_value=center_value
    self.right_value=right_value
    self.center_both=center_both
    self.center_neither=center_neither
    self.center_own=center_own
    self.default=default
    self.state=default

  def get_value(self):
    if(self.state=='l'):
      return([self.left_value])
    elif(self.state=='r'):
      return([self.right_value])
    elif(self.state=='c'):
      if(self.center_both):
        return([self.left_value,self.right_value])
      if(self.center_neither):
        return([])
      if(self.center_own):
        return([self.center_value])

  def set_state(self,new):
    if(new=='l' or
       new=='r' or
       new=='c'):
      self.state=new
    else:
      self.state=self.default

  def toggle(self):
    if(self.state=='l'):
      self.state='c'
    elif(self.state=='c'):
      self.state='r'
    elif(self.state=='r'):
      self.state='l'
    else:
      self.state=self.default

  def show(self):
    if(self.state=='l'):
      return(self.left_name+' (*) ( ) '+self.right_name)
    elif(self.state=='r'):
      return(self.left_name+' ( ) (*) '+self.right_name)
    elif(self.state=='c'):
      if(self.center_both):
        return(self.left_name+' (*) (*) '+self.right_name)
      elif(self.center_neither):
        return(self.left_name+' ( ) ( ) '+self.right_name)
      elif(self.center_own):
        return(self.left_name+' (*) (*) '+self.right_name)

# spot class
class SPOT:
  def __init__(self,stuff):
    self.stuff=stuff

  def band(self):
    return(band(self.freq))

  def age(self):
    offset=time.timezone if (time.localtime().tm_isdst==0) else time.altzone
    return(int(time.time()-self.spottime.timestamp()+offset))

# pota class
class POTA(SPOT):
  def __init__(self,stuff):
    SPOT.__init__(self,stuff)
    self.kind='POTA'
    self.id=mmh3.hash(clean_call(stuff['activator'])+'/'+
                      stuff['reference'])
    self.spotid=int(stuff['spotId'])
    self.activator=clean_call(stuff['activator'])
    self.freq=float(stuff['frequency'])*1000.0
    self.reference=stuff['reference']
    self.parkname=stuff['parkName']
    self.spottime=parse(stuff['spotTime'],fuzzy=True)
    self.spotter=stuff['spotter']
    self.comments=stuff['comments']
    self.source=stuff['source']
    self.invalid=stuff['invalid']
    self.name=stuff['name']
    self.locationdesc=stuff['locationDesc']
    self.grid4=stuff['grid4']
    self.grid6=stuff['grid6']
    self.latitude=float(stuff['latitude'])
    self.longitude=float(stuff['longitude'])
    self.count=int(stuff['count'])
    self.expire=int(stuff['expire'])
    if(stuff['mode']==''):
      self.mode='UNK'
    else:
      self.mode=stuff['mode']

  def band(self):
    return(band(self.freq))

  def json(self):
    return(json.dumps(self.stuff,indent=2))

  def oneline(self):
    return(self.kind+':'+
          str(self.id)+':'+
          str(self.spotid)+':'+
          self.activator+':'+
          self.locationdesc+':'+
          self.reference+':'+
          str(self.freq/1000.0)+':'+
          self.mode+
          '             ')

def fixer(thing):
  if(not(thing) or (thing=='')):
    return(0)
  else:
    return(thing)

# sota class
class SOTA(SPOT):
  def __init__(self,stuff):
    SPOT.__init__(self,stuff)
    self.kind='SOTA'
    self.id=mmh3.hash(clean_call(stuff['activatorCallsign'])+'/'+
                      stuff['associationCode']+'/'+stuff['summitCode']+'/'+
                      band(float(fixer(stuff['frequency']))*1000000.0))
    self.spotid=int(stuff['id'])
    self.spotid=int(stuff['id'])
    self.activator=clean_call(stuff['activatorCallsign'])
    self.freq=float(fixer(stuff['frequency']))*1000000.0
    self.reference=stuff['associationCode']+'/'+stuff['summitCode']
    self.spottime=parse(stuff['timeStamp'],fuzzy=True)
    self.name=stuff['activatorName']
    self.locationdesc=stuff['summitDetails']
    self.comments=stuff['comments']
    if(stuff['mode']==''):
      self.mode='UNK'
    else:
      self.mode=stuff['mode']

  def band(self):
    return(band(self.freq))

  def json(self):
    return(json.dumps(self.stuff,indent=2))

  def oneline(self):
    return(self.kind+':'+
          str(self.id)+':'+
          str(self.spotid)+':'+
          self.activator+':'+
          self.locationdesc+':'+
          self.reference+':'+
          str(self.freq/1000.0)+':'+
          self.mode+
          '             ')

def spots_thread(name):
  global spots_lock
  global spots
  global updating
  global refresh
  
  while True:
    spots=[]
    with spots_lock:
      updating=True
      log('updating')
      r=requests.get('https://api.pota.app/spot/activator')
      if(r.status_code==200 or r.status_code==201):
        stuff=json.loads(r.text)
        for p in stuff:
          spots.append(POTA(p))
      r=requests.get('https://api2.sota.org.uk/api/spots/50/all%7Call')
      if(r.status_code==200 or r.status_code==201):
        stuff=json.loads(r.text)
        for s in stuff:
          spots.append(SOTA(s))
      log('updating_complete')
      updating=False
    time.sleep(refresh)

def heard_it(current):
  global spots
  global worked
  global unheard
  global heard
  if(current):
    spot=list(filter(lambda s: s.id==current,spots))[0]
    heard.append(current)
    unheard=list(filter(lambda i: i!=current,unheard))
    worked=list(filter(lambda i: i!=current,worked))
    log('heard:'+spot.oneline())

def worked_it(current):
  global spots
  global worked
  global unheard
  global heard
  if(current):
    spot=list(filter(lambda s: s.id==current,spots))[0]
    worked.append(current)
    unheard=list(filter(lambda i: i!=current,unheard))
    heard=list(filter(lambda i: i!=current,heard))
    log('worked:'+spot.oneline())

def cannot_hear(current):
  global spots
  global worked
  global unheard
  global heard
  if(current):
    spot=list(filter(lambda s: s.id==current,spots))[0]
    unheard.append(current)
    worked=list(filter(lambda i: i!=current,worked))
    heard=list(filter(lambda i: i!=current,heard))
    log('cannot_hear:'+spot.oneline())

def radio_tune(current):
  global spots
  global rig
  if(current):
    spot=list(filter(lambda s: s.id==current,spots))[0]
    log('tune:'+spot.oneline())
    rig.set_freq(Hamlib.RIG_VFO_A,spot.freq)
    rig.set_vfo(Hamlib.RIG_VFO_A)
    if(spot.mode=='CW'):
          rig.set_mode(Hamlib.RIG_MODE_CW)
    elif(spot.mode=='SSB'):
      if(spot.freq>=10000000):
        rig.set_mode(Hamlib.RIG_MODE_USB)
      else:
        rig.set_mode(Hamlib.RIG_MODE_LSB)

def find_ref(ref,choices):
  return(sorted(list(map(lambda c: ref.find(c),choices)),reverse=True)[0]==0)

def main_menu(stdscr):
  global debug
  global worked
  global unheard
  global heard

  y=0
  k=0
  n=0
  current=False
  cursor_x=0
  cursor_y=0
  y_offset=2
  displayed=False
  blank='               '
  gone_freqs=[3500000.0,7000000.0,10000000.0,14000000.0]

  spots_us=['K0M','KH0','KH2','KH6','KP4','W0C','W0D','W0I','W0M','W0N','W1','W2','W3'
            'W4A','W4C','W4G','W4K','W4T','W4V','W5A','W5M','W5N','W5O','W5T','W6','W7A'
            'W7I','W7M','W7N','W7O','W7U','W7W','W7Y','W8M','W8O','W8V','W9',
            'US-']
  spots_na=['K0M','KH0','KH2','KH6','KP4','W0C','W0D','W0I','W0M','W0N','W1','W2','W3'
            'W4A','W4C','W4G','W4K','W4T','W4V','W5A','W5M','W5N','W5O','W5T','W6','W7A'
            'W7I','W7M','W7N','W7O','W7U','W7W','W7Y','W8M','W8O','W8V','W9'
            'VE1','VE2','VE3','VE4','VE5','VE6','VE7','VE9','VO1','VO2','VY1','VY2'
            'XE1','XE2','XE3',
            'US-','MX-','CA-']
  spots_ca_mx=['VE1','VE2','VE3','VE4','VE5','VE6','VE7','VE9','VO1','VO2','VY1','VY2'
               'XE1','XE2','XE3',
               'MX-','CA-']

  mode=Three('CW',False,'SSB',
             'CW',False,'SSB',
             True,False,False,'c')
  kinds=Three('SOTA',False,'POTA',
              ['SOTA'],['SOTA','POTA'],['POTA'],
              False,False,True,'c')
  loc=Three('US',False,'MX/CA',
            spots_us,spots_na,spots_ca_mx,
            False,False,True,'c')
  sorting=Two('Freq','Time',
              'freq','time',
              'l')
  bands=Two('Mobile','All',
#            ['forty','thirty','twenty','seventeen','fifteen','twelve','ten'],
            ['twenty','seventeen','fifteen','twelve','ten'],
            ['eighty','sixty','forty','thirty','twenty','seventeen','fifteen','twelve','ten','unknown'],
           'r')

  # Clear and refresh the screen for a blank canvas
  stdscr.clear()
  stdscr.refresh()
  stdscr.nodelay(1)
  curses.cbreak()
  curses.noecho()

  # curses colors
  curses.start_color()
  curses.init_pair(1,curses.COLOR_GREEN,curses.COLOR_BLACK)
  curses.init_pair(2,curses.COLOR_RED,curses.COLOR_BLACK)
  curses.init_pair(3,curses.COLOR_WHITE,curses.COLOR_BLACK)
  curses.init_pair(4,curses.COLOR_YELLOW,curses.COLOR_BLACK)
  curses.init_pair(5,curses.COLOR_BLUE,curses.COLOR_BLACK)

  while (k != ord('Q') and k != ord('q')):
    # Initialization
    stdscr.clear()
    height,width=stdscr.getmaxyx()

    big_blank=' '*(width-47-1)
    full_blank=' '*(width-1)

    stdscr.addstr(y_offset,5,'Type',curses.color_pair(3))
    stdscr.addstr(y_offset,10,' Call',curses.color_pair(3))
    stdscr.addstr(y_offset,20,' Ref',curses.color_pair(3))
    stdscr.addstr(y_offset,35,' Freq',curses.color_pair(3))
    stdscr.addstr(y_offset,45,' Mode',curses.color_pair(3))
    stdscr.addstr(y_offset,52,' Age',curses.color_pair(3))
    stdscr.addstr(y_offset,59,' Descr',curses.color_pair(3))
    y_offset=y_offset+1
    stdscr.addstr(y_offset,5,'----',curses.color_pair(3))
    stdscr.addstr(y_offset,10,' ----',curses.color_pair(3))
    stdscr.addstr(y_offset,20,' ---',curses.color_pair(3))
    stdscr.addstr(y_offset,35,' ----',curses.color_pair(3))
    stdscr.addstr(y_offset,45,' ----',curses.color_pair(3))
    stdscr.addstr(y_offset,52,' ---',curses.color_pair(3))
    stdscr.addstr(y_offset,59,' -----',curses.color_pair(3))
    y_offset=y_offset+1

    while (k != ord('Q') and k != ord('q')):
      now=time.time()
      with spots_lock:
        ls=len(spots)
        displayed=array.array('i',[])
        if(ls>0):
          y=0
          things=False
          if(sorting.get_value()[0]=='freq'):
            things=sorted(spots,key=lambda s: s.freq)
          else:
            things=sorted(spots,key=lambda s: s.age())
          for spot in things:
            if((find_ref(spot.reference,loc.get_value()[0])) and
                (spot.mode in mode.get_value()) and
                (spot.kind in kinds.get_value()[0]) and
                (not (spot.freq in gone_freqs)) and
                (spot.band() in bands.get_value()[0]) and
                (spot.age()<=max_age) and
                (spot.band()!="unknown") and
                (not (spot.id in displayed))):
              displayed.append(spot.id)
              if(not(spot.id in allspots)):
                allspots.append(spot.id)
                log('added:'+spot.oneline())
              if(spot.id in worked):
                color=1 # green for worked
              elif(spot.id in unheard):
                color=2 # red for unheard
              elif(spot.id in heard):
                color=4 # yellow for heard
              else:
                color=3 # white for untouched
              if(current==spot.id):
                stdscr.addstr(y+y_offset,0,'-->',curses.color_pair(color))
              else:
                stdscr.addstr(y+y_offset,0,'   ',curses.color_pair(color))
              stdscr.addstr(y+y_offset,5,spot.kind+blank,curses.color_pair(color))
              stdscr.addstr(y+y_offset,10,' '+spot.activator+blank,curses.color_pair(color))
              stdscr.addstr(y+y_offset,20,' '+spot.reference+blank,curses.color_pair(color))
              stdscr.addstr(y+y_offset,35,' '+str(spot.freq/1000.0)+blank,curses.color_pair(color))
              stdscr.addstr(y+y_offset,45,' '+spot.mode+blank,curses.color_pair(color))
              stdscr.addstr(y+y_offset,52,' '+str(spot.age())+big_blank,curses.color_pair(color))
              stdscr.addstr(y+y_offset,59,' '+spot.locationdesc+big_blank,curses.color_pair(color))
              if(y<height-y_offset-7):
                y=y+1
      for n in range(height-y-y_offset-6):
        stdscr.addstr(y+n+y_offset,0,full_blank,curses.color_pair(color))
      k=stdscr.getch()
      if(k==-1):
        time.sleep(0.25)
      elif(k==ord('m') or k==ord('M')):
        mode.toggle()
      elif(k==ord('l') or k==ord('L')):
        loc.toggle()
      elif(k==ord('b') or k==ord('B')):
        bands.toggle()
      elif(k==ord('w') or k==ord('W')):
        worked_it(current)
      elif(k==ord('c') or k==ord('C')):
        cannot_hear(current)
      elif(k==ord('h') or k==ord('H')):
        heard_it(current)
      elif(k==ord('s') or k==ord('S')):
        kinds.toggle()
      elif(k==ord('o') or k==ord('O')):
        sorting.toggle()
      elif(k==ord('r') or k==ord('R')):
        worked=list(filter(lambda i: i!=current,worked))
        unheard=list(filter(lambda i: i!=current,unheard))
        heard=list(filter(lambda i: i!=current,heard))
      elif(k==ord('t') or k==ord('T')):
        radio_tune(current)
      elif(k==ord('X')):
        worked=[]
        unheard=[]
        heard=[]
      elif(k==ord('D')):
        debug=not(debug)
      elif(k==ord('j')):
        with spots_lock:
          if(not(current) and len(displayed)>0):
            current=displayed[0]
          else:
            if(current in displayed):
              n=displayed.index(current)
              if(n<len(displayed)-1):
                current=displayed[n+1]
              else:
                current=displayed[0]
            else:
              current=False
      elif(k==ord('k')):
        with spots_lock:
          if(not(current) and len(displayed)>0):
            current=displayed[0]
          else:
            if(current in displayed):
              n=displayed.index(current)
              if(len(displayed)>n-1):
                current=displayed[n-1]
              else:
                current=displayed[len(displayed)-1]
            else:
              current=False

      stdscr.addstr(height-5,0,'O:  '+sorting.show(),curses.color_pair(4))
      stdscr.addstr(height-4,0,'S:  '+kinds.show(),curses.color_pair(4))
      stdscr.addstr(height-3,0,'M:  '+mode.show(),curses.color_pair(4))
      stdscr.addstr(height-2,0,'L:  '+loc.show(),curses.color_pair(4))
      stdscr.addstr(height-1,0,'B:  '+bands.show(),curses.color_pair(4))

      stdscr.addstr(height-5,30,'T:  Tune',curses.color_pair(4))
      stdscr.addstr(height-4,30,'C:  Cannot Hear',curses.color_pair(4))
      stdscr.addstr(height-3,30,'W:  Worked',curses.color_pair(4))
      stdscr.addstr(height-2,30,'H:  Heard',curses.color_pair(4))
      stdscr.addstr(height-1,30,'R:  Reset Spot',curses.color_pair(4))

      if updating:
        stdscr.addstr(0,0,'***UPDATING***'+full_blank,curses.color_pair(2))
      else:
        if(debug):
          stdscr.addstr(0,0,
                        'Displayed:'+
                        str(len(list(filter(lambda s: s.kind=='SOTA',spots))))+' '+
                        'SOTA:'+
                        str(len(list(filter(lambda s: s.kind=='POTA',spots))))+' '+
                        'POTA:'+
                        str(len(displayed))+full_blank,curses.color_pair(3))
        else:
          stdscr.addstr(0,0,blank,curses.color_pair(2))
      stdscr.refresh()

if __name__ == '__main__':
  parser=argparse.ArgumentParser(description="SOTA/POTA Monitor/Tuner")
  parser.add_argument("--no_radio",default=False,action="store_true",help="Pretend to work")
  parser.add_argument("--debug",default=False,action="store_true",help="Debug mode")
  parser.add_argument("--no_curses",default=False,action="store_true",help="No curses")
  parser.add_argument("--max_age",default=False,help="Max spot age in seconds (default 600)")
  args=parser.parse_args()

  if(args.debug):
    debug=True
  else:
    debug=False
    
  # log file
  logfile=open('/tmp/spota.log','a+')

  Hamlib.rig_set_debug(Hamlib.RIG_DEBUG_NONE)

  if(args.no_radio):
    rig=Hamlib.Rig(Hamlib.RIG_MODEL_DUMMY)
  else:
    rig=Hamlib.Rig(Hamlib.RIG_MODEL_IC7300)
   
  rig.set_conf('rig_pathname','/dev/ttyUSB0')
  rig.set_conf('serial_speed','19200')
  rig.set_conf('retry','5')
  rig.open ()

  log(Hamlib.rigerror(rig.error_status))

  thread1=Thread(target=spots_thread,args=('Spots Thread',),daemon=True)
  thread1.start()

  if(args.max_age):
    max_age=int(args.max_age)

  if(args.no_curses):
    while True:
      print(len(spots))
      time.sleep(1)

  curses.wrapper(main_menu)
