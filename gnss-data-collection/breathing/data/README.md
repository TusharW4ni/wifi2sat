## Manifest file
The manifest file is a file containing the metadata for the corresponding session and samples collected during the session.
The following are the info carried by the file:
- Metadata of the session
  - session id (session)
  - start utc of session (created_utc)
  - distance from reciever (distance_ft)
  - angle from east (angle_deg)
  - height of subject (person_height)
  - chest height of the subject (chest_height)
  - chest width of the subject (chest_width)
  - upper chest height of the subject (upper_chest_height)
  - lower chest height of the subject (lower_chest_height)
  - condition string (condition)
  - reps 
  - mode
- Metadata of each sample
  - session id (session)
  - condition string (condition)
  - window index (window_index)
  - rep 
  - start utc of rep (actual_utc)
  - corresponding rtcm file (rtcm)
  - corresponding json file (meta)

## JSON File
The json file corresponding to each sample has the meta data of the sample, which includes metadata and 
health check of each satellite.
The following are included in the file:
- Metadata of sample
  - Sample label (label)
  - start utc (capture_start_utc)
  - corresponding rtcm file (rtcm)
