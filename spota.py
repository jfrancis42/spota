#!/usr/bin/env python3
# coding: utf-8

# Copyright 2025
# Jeff Francis, N0GQ
# gjfrancis@protonmail.com
# https://github.com/jfrancis42/spota

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
import pathlib
import Hamlib

global spots_lock
global spots
global rig_lock
global rig
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
global hide
global allspots
global debug
global rig_freq
global rig_mode
global autohide
global no_curses

debug=False
autohide=False
no_curses=False
spots=array.array('i',[])
allspots=[]
worked=[]
unheard=[]
heard=[]
hide=[]
updating=False
spots_lock=threading.Lock()
rig_lock=threading.Lock()
s=False
refresh=60
max_age=600

# Write stuff to the log file.
def log(stuff):
  global logfile
  logfile.write(str(datetime.datetime.now())+':'+stuff+'\n')
  logfile.flush()

# Given a frequency in hz, return the band. Note that this assumes US
# bandplan. Note that it also doesn't distinguish between 75 and 80.
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

# Remove any prefixes and/or suffixes from a ham call to clean it up
# for display.
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

# Generic spot class to be inherited from.
class SPOT:
  def __init__(self,stuff):
    self.stuff=stuff

  def band(self):
    return(band(self.freq))

  def age(self):
    offset=time.timezone if (time.localtime().tm_isdst==0) else time.altzone
    return(int(time.time()-self.spottime.timestamp()+offset))

# POTA class. In the POTA API, the spotid does not stay constant for a
# given operator in a given park on a given day. If he gets
# re-spotted, he gets a new spotid. Hence, instead of using spotid as
# a reference, we do a fast, non-cryptographic hash on his callsign
# and park number. That way, when new spots come in for the same
# activation, we keep the same reference. Which makes handling the GUI
# approximately one zillion times easier.
class POTA(SPOT):
  def __init__(self,stuff):
    SPOT.__init__(self,stuff)
    self.kind='POTA'
    # POTA station is eligible for more contacts if he changes bands,
    # so don't hash the band.
    self.id=mmh3.hash(clean_call(stuff['activator'])+'/'+
                      stuff['reference'])
    self.spotid=int(stuff['spotId'])
    self.activator=clean_call(stuff['activator'])
    self.freq=float(stuff['frequency'])*1000.0
    self.reference=stuff['reference']
    self.loc=stuff['reference']
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

  def json(self):
    return(json.dumps(self.stuff,indent=2))

  def log_string(self):
    return(self.kind+':'+
           str(self.id)+':'+
           str(self.spotid)+':'+
           self.activator+':'+
           self.locationdesc+':'+
           self.reference+':'+
           str(self.freq/1000.0)+':'+
           self.mode+
           '             ')

  def worked_string(self):
    return(self.kind+':'+
           str(datetime.datetime.now())+':'+
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
    # SOTA station is one and done per peak, so include the band.
    self.id=mmh3.hash(clean_call(stuff['activatorCallsign'])+'/'+
                      stuff['associationCode']+'/'+stuff['summitCode']+'/'+
                      band(float(fixer(stuff['frequency']))*1000000.0))
    self.spotid=int(stuff['id'])
    self.activator=clean_call(stuff['activatorCallsign'])
    self.freq=float(fixer(stuff['frequency']))*1000000.0
    self.reference=stuff['associationCode']+'/'+stuff['summitCode']
    self.loc=stuff['associationCode']
    self.spottime=parse(stuff['timeStamp'],fuzzy=True)
    self.name=stuff['activatorName']
    self.locationdesc=stuff['summitDetails']
    self.comments=stuff['comments']
    if(stuff['mode']==''):
      self.mode='UNK'
    else:
      self.mode=stuff['mode']

  def json(self):
    return(json.dumps(self.stuff,indent=2))

  def log_string(self):
    return(self.kind+':'+
           str(self.id)+':'+
           str(self.spotid)+':'+
           self.activator+':'+
           self.locationdesc+':'+
           self.reference+':'+
           str(self.freq/1000.0)+':'+
           self.mode+
           '             ')

  def worked_string(self):
    return(self.kind+':'+
           str(datetime.datetime.now())+':'+
           str(self.spotid)+':'+
           self.activator+':'+
           self.locationdesc+':'+
           self.reference+':'+
           str(self.freq/1000.0)+':'+
           self.mode+
           '             ')

# This thread runs forever, periodically saving state.
def state_thread(name):
  global spots_lock
  global worked
  global heard
  global unheard
  global hide
  
  while True:
    with spots_lock:
      s=open(str(pathlib.Path.home())+'/spota.json','w+')
      s.write(json.dumps({'worked':worked,
                          'heard':heard,
                          'unheard':unheard,
                          'hide':hide},indent=2)+'\n')
      s.close()
    time.sleep(13)

# This thread runs forever, periodically fetching SOTA/POTA spots from
# their respective APIs.
def spots_thread(name):
  global spots_lock
  global spots
  global updating
  global refresh
  global no_curses
  
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

# Mark a spot as heard.
def heard_it(current):
  global spots
  global worked
  global unheard
  global heard
  if(current):
    with spots_lock:
      spot=list(filter(lambda s: s.id==current,spots))[0]
    heard.append(current)
    unheard=list(filter(lambda i: i!=current,unheard))
    worked=list(filter(lambda i: i!=current,worked))
    log('heard:'+spot.log_string())

# Mark a spot as hidden.
def hide_it(current):
  global spots
  global hide
  if(current):
    with spots_lock:
      spot=list(filter(lambda s: s.id==current,spots))[0]
    hide.append(current)
    log('hide:'+spot.log_string())

# Mark a spot as worked.
def worked_it(current):
  global spots
  global worked
  global unheard
  global heard
  global autohide
  if(current):
    with spots_lock:
      spot=list(filter(lambda s: s.id==current,spots))[0]
    worked.append(current)
    unheard=list(filter(lambda i: i!=current,unheard))
    heard=list(filter(lambda i: i!=current,heard))
    log('worked:'+spot.log_string())
    with open(str(pathlib.Path.home())+'/spota.worked','a+') as f:
      f.write(spot.worked_string()+'\n')
  if(autohide):
    hide_it(current)

# Mark a spot as 'can't hear'.
def cannot_hear(current):
  global spots
  global worked
  global unheard
  global heard
  global autohide
  if(current):
    with spots_lock:
      spot=list(filter(lambda s: s.id==current,spots))[0]
    unheard.append(current)
    worked=list(filter(lambda i: i!=current,worked))
    heard=list(filter(lambda i: i!=current,heard))
    log('cannot_hear:'+spot.log_string())
  if(autohide):
    hide_it(current)

# Tune the radio to this spot's frequency and mode.
def radio_tune(current):
  global spots
  global rig
  if(current):
    with spots_lock:
      spot=list(filter(lambda s: s.id==current,spots))[0]
    with rig_lock:
      log('tune:'+spot.log_string())
      rig.set_freq(Hamlib.RIG_VFO_A,spot.freq)
      rig.set_vfo(Hamlib.RIG_VFO_A)
      if(spot.mode=='CW'):
            rig.set_mode(Hamlib.RIG_MODE_CW)
      elif(spot.mode=='SSB'):
        if(spot.freq>=10000000):
          rig.set_mode(Hamlib.RIG_MODE_USB)
        else:
          rig.set_mode(Hamlib.RIG_MODE_LSB)

# See if the given ref matches one of the list of prefix choices.
def find_loc(loc,choices):
  return(sorted(list(map(lambda c: loc.find(c),choices)),reverse=True)[0]==0)

# Main loop of the program.
def main_menu(stdscr):
  global debug
  global worked
  global unheard
  global heard
  global hide
  global now
  global autohide

  y=0
  k=0
  n=0
  current=False
  cursor_x=0
  cursor_y=0
  y_offset=2
  displayed=False
  blank='               '

  # In the SOTA world, it's common for the activator to spot himself
  # with the 'base' frequency of the current band to let the world
  # know he's done.
  gone_freqs=[3500000.0,7000000.0,10000000.0,14000000.0]

  # These are the SOTA/POTA locators for North America.
  valid_locs=['K0M','KH0','KH2','KH6','KP4','W0C','W0D','W0I','W0M','W0N','W1','W2','W3',
              'W4A','W4C','W4G','W4K','W4T','W4V','W5A','W5M','W5N','W5O','W5T','W6','W7A',
              'W7I','W7M','W7N','W7O','W7U','W7W','W7Y','W8M','W8O','W8V','W9',
              'VE1','VE2','VE3','VE4','VE5','VE6','VE7','VE9','VO1','VO2','VY1','VY2',
              'XE1','XE2','XE3',
              'US-','MX-','CA-']

  # These are the bands I can work from home/portable.
  valid_bands=['eighty','sixty','forty','thirty','twenty',
                    'seventeen','fifteen','twelve','ten']

  # Add the various "switches" for switching and displaying of options
  # in the GUI.
  mode=Three('CW',False,'SSB',
             'CW',False,'SSB',
             True,False,False,'c')
  kinds=Three('SOTA',False,'POTA',
              ['SOTA'],['SOTA','POTA'],['POTA'],
              False,False,True,'c')
  sorting=Two('Freq','Time',
              'freq','time',
              'l')
  delete=Two('Auto','Manual',
              'auto','man',
              'l')

  # Clear and refresh the screen.
  stdscr.clear()
  stdscr.refresh()
  stdscr.nodelay(1)
  curses.cbreak()
  curses.noecho()

  # Add the colors we want to use.
  curses.start_color()
  curses.init_pair(1,curses.COLOR_GREEN,curses.COLOR_BLACK)
  curses.init_pair(2,curses.COLOR_RED,curses.COLOR_BLACK)
  curses.init_pair(3,curses.COLOR_WHITE,curses.COLOR_BLACK)
  curses.init_pair(4,curses.COLOR_YELLOW,curses.COLOR_BLACK)
  curses.init_pair(5,curses.COLOR_BLUE,curses.COLOR_BLACK)

  # Loop forever.
  while (k != ord('Q') and k != ord('q')):
    # Initialization
    stdscr.clear()
    height,width=stdscr.getmaxyx()

    # Blanks for clearing old stuff.
    big_blank=' '*(width-47-1)
    full_blank=' '*(width-1)

    # Add the column headers.
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

    # Loop until the user quits.
    while (k != ord('Q') and k != ord('q')):
      now=time.time()
      with spots_lock:
        ls=len(spots)
        displayed=array.array('i',[])
        if(ls>0):
          y=0
          # Sort by the user's preference.
          things=False
          if(sorting.get_value()[0]=='freq'):
            things=sorted(spots,key=lambda s: s.freq)
          else:
            things=sorted(spots,key=lambda s: s.age())
          for spot in things:
            # Display the spots as specified by user preferences.
            if((find_loc(spot.loc,valid_locs)) and
                (spot.mode in mode.get_value()) and
                (spot.kind in kinds.get_value()[0]) and
                (not (spot.freq in gone_freqs)) and
                (not (spot.id in hide)) and
                (spot.band() in valid_bands) and
                (spot.age()<=max_age) and
                (spot.band()!="unknown") and
                (not (spot.id in displayed))):
              displayed.append(spot.id)
              # TODO: We should probably add the latest spot by
              # timestamp rather than the first in the list.
              if(not(spot.id in allspots)):
                allspots.append(spot.id)
                log('added:'+spot.log_string())
              # Set the colors for each line.
              if(spot.id in worked):
                color=1 # green for worked
              elif(spot.id in unheard):
                color=2 # red for unheard
              elif(spot.id in heard):
                color=4 # yellow for heard
              else:
                color=3 # white for untouched
              # Make sure the cursor doesn't disappear.
              if(not(current) and len(displayed)>0):
                current=displayed[0]
              # Display the pointer for the currently selected spot.
              if(current==spot.id):
                stdscr.addstr(y+y_offset,0,
                              '-->',curses.color_pair(color))
              else:
                stdscr.addstr(y+y_offset,0,
                              '   ',curses.color_pair(color))
              # Display the fields for this spot.
              stdscr.addstr(y+y_offset,5,
                            spot.kind+blank,curses.color_pair(color))
              stdscr.addstr(y+y_offset,10,
                            ' '+spot.activator+blank,curses.color_pair(color))
              stdscr.addstr(y+y_offset,20,
                            ' '+spot.reference+blank,curses.color_pair(color))
              stdscr.addstr(y+y_offset,35,
                            ' '+str(spot.freq/1000.0)+blank,curses.color_pair(color))
              stdscr.addstr(y+y_offset,45,
                            ' '+spot.mode+blank,curses.color_pair(color))
              stdscr.addstr(y+y_offset,52,
                            ' '+str(spot.age())+big_blank,curses.color_pair(color))
              stdscr.addstr(y+y_offset,59,
                            ' '+spot.locationdesc+big_blank,curses.color_pair(color))
              # Increment down the screen until we run out of room.
              if(y<height-y_offset-7):
                y=y+1
      # Blank out the unused space.
      for n in range(height-y-y_offset-6):
        stdscr.addstr(y+n+y_offset,0,
                      full_blank,curses.color_pair(color))
      # Read the keyboard and process options.
      k=stdscr.getch()
      if(k==-1):
        time.sleep(0.25)
      elif(k==ord('m') or k==ord('M')):
        mode.toggle()
      elif(k==ord('w') or k==ord('W')):
        worked_it(current)
      elif(k==ord('c') or k==ord('C')):
        cannot_hear(current)
      elif(k==ord('h') or k==ord('H')):
        heard_it(current)
      elif(k==ord('s') or k==ord('S')):
        kinds.toggle()
      elif(k==ord('a') or k==ord('A')):
        delete.toggle()
        if(delete.get_value()[0]=='auto'):
          for s in unheard:
            hide_it(s)
          for s in worked:
            hide_it(s)
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
      elif(k==ord('i') or k==ord('I')):
        hide_it(current)
        current=False
      elif(k==ord('j')):
        with spots_lock:
          if(not(current) and len(displayed)>0):
            current=displayed[0]
            radio_tune(current)
          else:
            if(current in displayed):
              n=displayed.index(current)
              if(n<len(displayed)-1):
                current=displayed[n+1]
              else:
                current=displayed[0]
            else:
              current=False
        if(delete.get_value()[0]=='auto'):
          radio_tune(current)
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
        if(delete.get_value()[0]=='auto'):
          radio_tune(current)

      if(delete.get_value()[0]=='auto'):
        autohide=True
      else:
        autohide=False

      # Display the menu at the bottom.
      stdscr.addstr(height-5,0,'O:  '+sorting.show(),curses.color_pair(4))
      stdscr.addstr(height-4,0,'S:  '+kinds.show(),curses.color_pair(4))
      stdscr.addstr(height-3,0,'M:  '+mode.show(),curses.color_pair(4))
      stdscr.addstr(height-2,0,'A:  '+delete.show(),curses.color_pair(4))
#      stdscr.addstr(height-1,0,'L:  '+loc.show(),curses.color_pair(4))
      stdscr.addstr(height-5,30,'T:  Tune',curses.color_pair(4))
      stdscr.addstr(height-4,30,'C:  Cannot Hear',curses.color_pair(4))
      stdscr.addstr(height-3,30,'W:  Worked',curses.color_pair(4))
      stdscr.addstr(height-2,30,'H:  Heard',curses.color_pair(4))
      stdscr.addstr(height-1,30,'R:  Reset Spot',curses.color_pair(4))

      # Let the user know if we're fetching fresh data from the APIs.
      if updating:
        stdscr.addstr(0,0,'***UPDATING***'+full_blank,curses.color_pair(2))
      else:
        # Show the debug info, if requested.
        if(debug):
          stdscr.addstr(0,0,
                        'Displayed:'+
                        str(len(displayed))+' '+
                        'SOTA:'+
                        str(len(list(filter(lambda s: s.kind=='SOTA',spots))))+' '+
                        'POTA:'+
                        str(len(list(filter(lambda s: s.kind=='POTA',spots))))+' '+
#                        'displayed:'+
#                        str(displayed)+' '+
                        full_blank,curses.color_pair(3))
        else:
          stdscr.addstr(0,0,full_blank,curses.color_pair(2))
      # Refresh anything added to the screen and start again.
      stdscr.refresh()

if __name__ == '__main__':
  # Process the command line arguments.
  parser=argparse.ArgumentParser(description='SOTA/POTA Monitor/Tuner')
  parser.add_argument('--no_radio',default=False,action='store_true',help='Pretend to work')
  parser.add_argument('--debug',default=False,action='store_true',help='Debug mode')
  parser.add_argument('--no_curses',default=False,action='store_true',help='No curses')
  parser.add_argument('--no_state',default=False,action='store_true',help='Do not load state')
  parser.add_argument('--max_age',default=False,help='Max spot age in seconds (default 600)')
  args=parser.parse_args()

  # Turn on debug if the user wants it.
  if(args.debug):
    debug=True
  else:
    debug=False
    
  # Open the log file.
  logfile=open(str(pathlib.Path.home())+'/spota.log','a+')

  # Don't spew debug info to stdout.
  Hamlib.rig_set_debug(Hamlib.RIG_DEBUG_NONE)

  # Allow the user to run without a selected radio. Note: This is
  # where you add your own radio and serial info until I get around to
  # making it configurable.
  if(args.no_radio):
    print('Connecting to dummy radio...')
    rig=Hamlib.Rig(Hamlib.RIG_MODEL_DUMMY)
  else:
    print('Connecting to radio...')
    rig=Hamlib.Rig(Hamlib.RIG_MODEL_IC7300)
    rig.set_conf('rig_pathname','/dev/ttyUSB0')
    rig.set_conf('serial_speed','19200')
    rig.set_conf('retry','5')
   
  # Connect to the radio.
  rig.open ()

  # Send radio data to the log.
  log(Hamlib.rigerror(rig.error_status))

  # Set the max age of displayed spots, if selected.
  if(args.max_age):
    max_age=int(args.max_age)

  # Load state data.
  if(not(args.no_state)):
    print('Loading state...')
    if(os.path.isfile(str(pathlib.Path.home())+'/spota.json')):
      with open(str(pathlib.Path.home())+'/spota.json','r') as f:
        stuff=json.load(f)
        worked=stuff['worked']
        heard=stuff['heard']
        unheard=stuff['unheard']
        hide=stuff['hide']

  # Start the thread to fetch spot data.
  print('Starting spot thread...')
  thread1=Thread(target=spots_thread,args=('Spots Thread',),daemon=True)
  thread1.start()

  # Start the thread to periodically save state.
  print('Starting state thread...')
  thread2=Thread(target=state_thread,args=('State Thread',),daemon=True)
  thread2.start()

  # This is sort of a debug mode.
  no_curses=args.no_curses
  if(no_curses):
    while True:
      print(len(spots))
      time.sleep(1)

  # Run the main loop.
  curses.wrapper(main_menu)
