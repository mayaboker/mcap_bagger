# App publisher port

Move the sample configuration's App blackboard channel subscriptions from port 5557 to 5558. The renderer owns port 5557 for control, so the App cannot bind there during SITL. Topic names, payloads, recording behavior, and other channel endpoints stay unchanged.

The sample configuration loads, its 11 blackboard endpoints match Bullet App's launch configuration, and 18 registration tests passed. Status: Complete.
