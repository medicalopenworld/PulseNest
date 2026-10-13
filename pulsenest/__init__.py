"""Host-side modules shared by every PulseNest program (the lab, the hub, the recorder, the tools).

Scripts outside the repo root put the root on sys.path with one line and import from here:

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
    from pulsenest.net import UDP_DATA_PORT
"""
