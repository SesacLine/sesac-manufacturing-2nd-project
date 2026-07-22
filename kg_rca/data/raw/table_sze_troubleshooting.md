# 반도체 전공정 5단계 트러블슈팅표

> 공정 단계별로 **품질측정(Quality Measures)** + **고장진단(Troubleshooting)** 표를 묶음.
> 페이지 기준: 원서(≤17장) / 한국어판(18장~). 표 내용은 원문 그대로.

---

# DEPO (Deposition)

> 산화(10장) · CVD 증착(11장) · 금속화(12장) 포함.

## p250-251
### TABLE 10.7 Quality Measures for Thermal Oxide Layer

| Quality Parameter | Types of Defects | Remarks |
|---|---|---|
| 1. Oxide thickness. | A. Thickness of gate oxide outside of specification (representative gate oxide specification is 20 ± 1.5 Å). | Possible reasons for this problem are:<br>- Incorrect process gas flow (e.g., MFC calibrated improperly). Since HCl enhances oxidation rate, verify HCl:O₂ ratio is correct.<br>- Verify O₂ leak integrity of the furnace with a bare silicon test wafer.<br>- Check the metrology equipment by measuring the oxide thickness against a standard thickness wafer.<br>- Excess native oxide growth due to overexposure of wafer to air either before or after normal furnace oxidation. |
| 2. Gate oxide integrity (GOI). | A. Gate oxide breakdown.<br>B. Mobile ionic contamination (MIC) in film. | Gate oxide defects are often related to processing conditions:<br>- Perform a C-V test to demonstrate gate oxide integrity using an unpatterned test wafer.<br>- Perform an oxide-charge analysis on a test wafer with a surface-charge analyzer.<br>- Review the preoxidation clean steps to assess sources of contamination (e.g., particles or MICs).<br>- Verify no contamination from an incoming gas line or defective filter. |
| 3. Particles in the oxide film. | A. Contaminated quartzware.<br>B. Wafer broken inside furnace.<br>C. Contaminated carrier.<br>D. Contaminated gas filter or line. | Actions to correct these sources of particles added during the oxidation process are:<br>- Check cleanliness of quartzware and carrier.<br>- Verify the alignment of the robotic handling systems.<br>- Check incoming gas filters. |
| 4. Particles under the oxide film. | A. Contaminated preoxidation clean. | Source of particles prior to the oxidation step are:<br>- Verify the preoxidation clean steps are properly set up and performed.<br>- Check cleanliness of quartzware and carrier. |

---

## p252
### TABLE 10.8 Common Oxidation Troubleshooting Problems

| Problem | Probable Causes | Corrective Actions |
|---|---|---|
| 1. Incorrect gas flow into furnace tube. | A. Incorrect process recipe.<br>B. Malfunctioning MFC.<br>C. Incorrect H₂:O₂ ratio for steam process (O₂ starved). | Possible corrective actions for this problem are:<br>- Verify that correct process recipe is downloaded into furnace software for the wafer being processed.<br>- Check process gas MFCs (O₂, N₂, H₂, Cl) to verify calibration was performed and operating properly.<br>- Verify gas valves are functioning properly (e.g., no leaks, and so on).<br>- Check that no room air is leaking into the furnace tube from outside the quartz or furnace door seal. |
| 2. Incorrect temperature uniformity in vertical furnace chamber. | A. Wrong process recipe for product.<br>B. Incorrect operation of thermocouples. | Possible corrective actions are:<br>- Verify that the correct process recipe is loaded for the wafer being processed.<br>- Assess whether the temperature nonuniformity is during the ramp up, flat zone, and ramp down for corrective action.<br>- Check all thermocouples for proper operation. Verify no degradation due to excessive heat or corrosion. Replace defective thermocouples. Verify no drift in thermocouple reference temperature. |
| 3. Inadequate temperature uniformity in rapid thermal processor (RTP). | A. Malfunctioning heating system (e.g., tungsten halogen lamps).<br>B. Verify correct operation of temperature measurement sensor. | Possible corrective actions are:<br>- Verify heating lamps are operating and have the correct lamp intensity.<br>- Verify correct calibration and temperature measurement of the optical pyrometer temperature sensor. Check there is no variation in wafer emissivity by performing reflectivity measurement of the wafer surface. |

---

## p292
### TABLE 11.7. Key Quality Measures for CVD

| Quality Parameter                                                              | Types of Defects                                                                                                                                                                                                                                                                  | Remarks                                                                                                                                                                                                                                                                                                                                                                           |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1. Voids during deposition of high-aspect ratio gap (>3:1) with PECVD SiO₂** | **A.** Keyhole voids are formed during deposition of high aspect ratio gaps. After chemical mechanical planarization (CMP) and removal of top surface, some voids become trenches (see Figure 11.31 on page 294). This trench can lead to an open circuit after metal deposition. | - Gap fill is critical as CDs are reduced and gaps have a high aspect ratio.<br>- Voids are highly stressed regions and trap moisture or solvents that cause corrosion or outgas at high vacuum.<br>- The root cause of this problem is trying to fill a high aspect ratio gap with a PECVD that is limited to deposition system. This application requires HDPCVD.               |
| **2. Film stress**                                                             | **A.** High film stress leads to cracking and delamination.<br>**B.** Film stress can propagate silicon defects in the substrate.<br>**C.** Stress may cause current leakage.                                                                                                     | The presence of dopant in a glass film can reduce stress. Deposition parameters that affect film stress are:<br>- **RF power:** adjust power to improve stress (e.g., reduce power by 10 watts to lower stress).<br>- **Pressure:** adjust pressure to affect stress (e.g. increased pressure leads to higher film stress).                                                      |
| **3. Film thickness**                                                          | **A.** Thickness of film exceeds requirements.                                                                                                                                                                                                                                    | Deposition parameters that affect thickness are:<br>- **Time:** reduce deposition time to reduce thickness (e.g., 1 sec reduction for each 100 Å of thickness).<br>- **Gas-flow rate:** reduce gas flow to reduce thickness (e.g., reduce SiH₄ by 2 sccm for >5% thickness over nominal).                                                                                         |
| **4. Refractive index (R/I)**                                                  | **A.** R/I is a good monitor to assess quality of the film.<br>**B.** R/I is highly dependent on the composition of the deposited film (stoichiometry).                                                                                                                           | R/I is an optical property of a material. Compared to thermal oxides, CVD oxides are inferior in quality and integrity. CVD oxides exhibit more particles and pinholes. The R/I of CVD SiO₂ can be compared to the R/I of SiO₂ (1.46) to assess relative quality:<br>- High R/I means excessive Si in film.<br>- Low R/I indicates a porous film, which tends to absorb moisture. |

---

## p293
### TABLE 11.8. Common CVD Troubleshooting Problems

| Problem | Probable Cause | Corrective Action |
| --- | --- | --- |
| **1. Particle contamination associated with film.** | Source of particles is isolated by determining whether particles are found on top of film, in film, or below film:<br>**A.** On film: particles formed after deposition. Check for particles on sidewalls of hot-wall reactors and belt-driven reactors.<br>**B.** In film: Gas-phase nucleation particles from gas too rich in silane or silicon. Gas supply contamination causes particles.<br>**C.** Under film: Particles from silicon carbide, quartz, or reactor walls fall on wafer before deposition. | - **Particles on film:** Particles on sidewalls indicate need for more frequent wet cleaning of quartzware and chamber surfaces for preventive maintenance. Inspect in situ dry cleaning process. Also verify the correct procedures for cleaning (manually or in situ).<br>- **Particles in film:** Improper gas flows from MFC calibration or problem in process recipe of software program. Check for leaks in gas supply system or O-rings. Verify point-of-use filters are acceptable.<br>- **Particles under film:** Check wafer cleaning process before deposition. |
| **2. Film thickness.** | Thickness is related to both equipment and process problems. Variables affecting thickness are:<br>**A.** Incorrect temperature control.<br>**B.** System pressure is too high or low.<br>**C.** System power needs adjustment.<br>**D.** Improper gas flow. | - Temperature controller may require calibration. A common problem is a defective thermocouple.<br>- System pressure is controlled by process recipe. Check vacuum system for leaks.<br>- Adjust RF power to optimize film thickness.<br>- Check calibration of MFC to ensure proper gas flow.<br>- If checking thickness with test wafer, verify the test wafer is clean and does not have a thickness variation before the test. |
| **3. Cracking of dielectric material on top of electrostatic chuck (ESC).** | High thermal load at the ESC causes the dielectric material to erode or crack. This condition leads to plasma arcing or wafer chucking/dechucking problems. | - Investigate the ESC backside cooling system to ensure it is functioning properly.<br>- Inspect ESC materials to verify there is no breakdown due to high power exposure, temperature, or plasma clean conditions. |

---

## p329
### TABLE 12.6 Quality Measures for Metallization

| Quality Parameter | Types of Defects | Remarks |
|---|---|---|
| 1. Sputtered metal adhesion. | A. Metal layer does not adhere to substrate. | Parameters affecting film adhesion are:<br>- Wafer contamination<br>- Stress<br>- Types of materials<br>- Temperature of substrate<br>- Argon pressure |
| 2. Sputtered film stress. | A. Excessive stress leads to:<br>- Cracks in the film surface.<br>- Loss of film adhesion.<br>- Increased resistivity in some materials. | Film stress can be caused by excessive temperature of the wafer substrate. Ways to reduce wafer temperature are:<br>- Lower deposition rate<br>- Increased backside cooling<br>Cracks can cause:<br>- Peeling of the film layer<br>- Contaminant migration<br>- Electrical opens or short.<br>Measure film stress (bow of wafer surface) before and after deposition. Units for stress are dynes. |
| 3. Sputtered film thickness. | A. Metal layer does not meet film thickness specifications (e.g., sheet resistance out of specification). | Parameters that affect film thickness are:<br>- Incorrect recipe<br>- Improper flow rates<br>- Improper substrate temperature<br>- Improper chamber pressure<br>- Improper power supply energy<br>- Wrong time setting |
| 4. Uniformity of electroplated (electrochemical deposition, or ECD) metal film. | A. Nonuniform film thickness indicated by:<br>- Inadequate gap fill and step coverage for high aspect ratio openings (nonuniform metal thickness at top and bottom of high aspect ratio holes).<br>- Nonuniform deposition thickness across the wafer and from wafer to wafer.<br>- Voids in film. | Critical parameters for electroplating film uniformity are:<br>- Depositing a uniform CVD seed layer without voids.<br>- Maintaining proper electroplating bath chemistry (composition and concentration) for organic additives, primarily brighteners and suppressors, to attain void-free deposition that fills bottom and sidewalls of gaps. |

---

## p330
### TABLE 12.7 Common Metallization Troubleshooting Problems

| Problem | Probable Cause | Corrective Actions |
|---|---|---|
| 1. Degradation in step coverage of metal film. | A. Decrease in substrate temperature. For Al alloy sputter deposition, step coverage is dependent on the wafer temperature during deposition. | Heating the substrate to improve step coverage because surface mobility of deposited metal atoms improves. |
| 1. Degradation in step coverage of metal film. | B. Increase in deposition rate. | Decrease deposition rate. Increase in sputter deposition rate may degrade step coverage due to reduced surface mobility because of arrival of more atoms at surface. |
| 2. Vacuum chamber integrity. | A. Chamber cleanliness or moisture in chamber. | - Check for vacuum leaks or chamber outgassing. Residual gas in chamber that can change film reflectivity.<br>- Check for O₂ or N₂ in metal films that can change resistivity and film stress.<br>- Clean chamber and do H₂O bake-out. |
| 2. Vacuum chamber integrity. | B. Outgassing or system leaks. | - Use helium leak detection to inspect for system leaks.<br>- Assess the chamber conditions before deposition with residual gas analyzer. |
| 3. Contamination of metal film. | A. Particles on surface of film. | Check the following common particle sources:<br>- Dirty input wafers.<br>- Problems in hand-off between robot and chamber mechanism.<br>- Incomplete chamber cleaning between runs.<br>- Dirty cassettes.<br>- Contaminated nitrogen backfill. |
| 4. Voids in copper trench fill after dual-damascene electroplating. | A. Excessive seed layer thickness on the wafer surface (field) that pinches off the via or trench, creating a center void in the film.* | Optimize the CVD Cu seed layer deposition by evaluating the electroplating current from the field to the bottom of vias and trenches. The goal is to deposit adequate seed layer at the bottom of a high-aspect ratio feature without increasing field thickness. |
| 5. Excessive copper dishing after dual-damascene CMP. | A. Cu dishing for Cu CMP is often caused by tantalum diffusion barrier, which must be polished back in the presence of Cu.** | After Cu is polished, the Ta layer must be removed from the level. The Cu pad/slurry field does not effectively remove Ta.<br>Options are:<br>- Optimize the pad/slurry for Ta.<br>- Minimize the Ta field level thickness. |

> \* R. Jackson et al., "Processing and Integration of Copper Interconnects," *Solid State Technology* (March 1998): p. 56.    
> \** Ibid.

---

# LITHO (Photolithography)

> 포토레지스트·스핀코트(13장) · 정렬·노출(14장) · 현상(15장) 포함.

## p362
### TABLE 13.6 Key Quality Measures for Photoresist

| Quality Parameter | Types of Defects | Remarks |
|---|---|---|
| **1. Resist adhesion.** | A. Resist dewetting, which is also called lift-off. The resist does not adhere to the substrate, causing problems during subsequent etch or ion implantation processing. | Possible causes of resist lift-off are:<br>- Contamination on wafer surface.<br>- Inadequate HMDS priming or dehydration bake resulting in moisture on wafer surface (measured by contact angle meter as described in Chapter 7).<br>- Excessive HMDS priming can cause resist "popping," which is failure of poorly adhered resist.<br>- SiO₂ is a difficult surface to achieve good adhesion because it is a hydrophilic surface (water attracting).* |
| **2. General quality of resist coating on wafer.** | A. Pinholes (very small holes) in the resist. | - Particulate contamination on mask/reticle (evident after exposure) or on wafer. Check surface preparation cleaning. |
| **2. General quality of resist coating on wafer.** | B. Splashback (drops of resist fall on resist coating). | - Improper exhaust level in spin coater.<br>- Adjust vacuum suckback on dispense nozzle to stop drops from forming and dripping on resist. |
| **2. General quality of resist coating on wafer.** | C. Resist skinning (thin layer of insoluble resist dried on top of resist coating). | - Spin rate is too high. High spin speeds can cause striations (lines) in the resist.<br>- Exhaust rate too high in spin coater.<br>- For DUV resists, ensure coated resist is not exposed to amines inside track system (check carbon filtration). |
| **3. Thickness of resist coating.** | A. Coated resist thickness is out of control. Resist thickness must be uniform: wafer-to-wafer mean thickness requirement is often <30 Å total indicated runout (TIR, which is maximum minus minimum thickness). | Parameters that affect thickness of resist are:<br>- Check spin acceleration and speed. Higher spin speeds produce thinner resist (recall that thickness is inversely proportional to the square root of spin speed). Verify spin speed versus thickness characteristic curve of resist manufacturer. At low spin speeds, irregular solvent loss leads to thickness nonuniformity.<br>- Verify correct spin time. Resist reaches stable thickness in several seconds and requires additional time for thickness uniformity.<br>- Check for correct resist type and viscosity.<br>- Verify no mechanical vibration or air turbulence during high speed spin dry. |

> *\* B. Smith, "Resist Processing," Microlithography, Science and Technology, ed. J. Sheats and B. Smith, (New York: Marcel Dekker, 1998), p. 529.*

---

## p363
### TABLE 13.7. Common Photoresist Troubleshooting Problems

| Problem | Probable Cause | Corrective Actions |
| --- | --- | --- |
| **1. Excessive resist usage during spin coating (DUV resist costs $2,000 to $5,000 per gallon).** | **A.** Sub-optimum setting of process variables during spin coating process. | Optimize process variables for spin coating:<br>- First, determine minimum volume of resist needed to coat the wafer (referred to as cut-off volume).<br>- Second, evaluate the following critical parameters using design of experiments: dispense spin speed, exhaust flow rate during dispense and drying steps, dispense rate, resist temperature, cool plate temperature, and ambient air temperature. |
| **1. Excessive resist usage during spin coating (DUV resist costs $2,000 to $5,000 per gallon).** | **B.** Improper spin coater tool setup. | Check the spin coater setup for the following:<br>- Incorrect nozzle size, height, or position.<br>- Calibration of coater equipment.<br>- Wrong software process recipe for wafer. |
| **2. Wafers damaged (broken or chipped) during normal processing in the wafer track.** | **A.** Improper setup of different tools used in track for processing wafers. | Check the following equipment for proper setup:<br>- Improper calibration of robot arms during wafer handoff from one track tool to another.<br>- Loss of chuck vacuum during spin.<br>- Spin coat machine is not leveled properly and has mechanical vibration.<br>- Excessive spin speed.<br>- Verify calibration of cassette indexer to index wafers in cassette for robot pickup.<br>- Warped cassettes cause equipment malfunction. |
| **3. DNQ-novolak resist becomes unstable and contaminated with articles.** | **A.** DNQ-novolak resist has aged due to shelf life. | Excessive shelf life of DNQ-novolak resist (> several months, with maximum of six months to one year) can lead to the following:\*\*<br>- Increase in absorption at longer wavelengths.<br>- Susceptible to thermal degradation of the DNQ, leading to crosslinking and increase of high molecular-weight resist components.<br>- Formation of undesirable acids in the resist.<br>- Precipitation (falling out of solution) of sensitizer to form crystallized particles that contaminate resists. This especially occurs at high-temperature storage.<br>- Point-of-use filtration is common practice for production applications to control resist consistency. Typical filter size is 0.05 μm for 0.25 μm feature size. |

> \* B. Lorefice et al., "How to Minimize Resist Usage During Spin Coating," *Semiconductor International* (June 1998): p. 182.    
> \*\* B. Smith, "Resist Processing," *Microlithography, Science and Technology*, ed. J. Sheats and B. Smith.

---

## p407-408
### TABLE 14.8 Key Quality Measures for Exposure

| Quality Parameter | Types of Defects | Remarks |
|---|---|---|
| 1. Focus-exposure dose. | A. Incorrect focus-exposure for system. Conduct focus-exposure optimization test while measuring CD linewidth. | - Verify uniform and optimum exposure from illumination source.<br>- Make CD measurements of line versus a series of exposure dose values for a nominal focal position (e.g., 30% from top surface).<br>- With nominal focal position, find optimum dose for producing CD.<br>- Modify focal position and conduct CD measurements. Wide range of acceptable dose exposure at optimum focal position.<br>- Verify the bulk resist meets all quality parameters. |
| 2. Light intensity of illumination source. | A. Non-uniform light intensity in the exposure field. | - Check light intensity for specified energy and uniformity at several locations on a wafer. Most aligners have built-in photodetector (measures in mW/cm²).<br>- Evaluate resist to ensure it is not outgassing and condensing on optical elements. This will degrade lens transmission and field uniformity (important for DUV resists).* |
| 3. Reticle alignment in stepper or step-and-scan tool. | A. Reticle alignment targets will not align properly with wafer alignment targets. | - Verify appropriate process recipe is loaded for the specific mask layer.<br>- Verify appropriate wafers and reticle are loaded for a specific job.<br>- Check rotation of reticle on reticle stage or wafer on wafer stage due to vacuum leak at chuck or electromechanical problem with stage.<br>- Problem with internal optics of aligner. Possible cause is temperature or pressure change that affects the NA of the lens. |
| 4. Pattern resolution. | A. Poor resolution for CDs on wafer: linewidths and holes do not meet specification. | Resolution is often a focus problem:<br>- Perform focus-exposure test.<br>- Check environment (temperature, pressure).<br>- Wafer is not flat on chuck, possibly due to backside contamination or chuck problem.<br>- Look for possible incoming process-related problems or improper process parameters or reticle.<br>- Look for optics problems (e.g., lens aberrations). |
| 5. Reticle quality. | The following are reticle defects:<br>A. Dirt or scratches on reticle.<br>B. Pattern defects on reticles:<br>&nbsp;&nbsp;- Break in line.<br>&nbsp;&nbsp;- Bridge between features.<br>&nbsp;&nbsp;- Missing geometry.<br>&nbsp;&nbsp;- Opaque spot from isolated chrome.<br>&nbsp;&nbsp;- Pinhole in chrome line.<br>C. Glass fracture.<br>D. Lifted chrome (poor adhesion).<br>E. Reticle plate flatness. | - Scratches can remove chrome and cause defect in resist.<br>- A break in line extends completely across the chrome feature.<br>- Bridge will join two chrome features across a clear space on the reticle.<br>- Missing geometry is a pattern not on reticle, such as a missing contact.<br>- Opaque spot is an area of chrome that should not be on reticle.<br>- Pinhole is a hole in a chrome pattern.<br>- Reticles should not have fractures and be controlled for flatness and warpage. |

> *O. Nalamasu et al., "Single-Layer Resist Design for 193 nm Lithography," *Solid State Technology* (May 1999), p. 29.

---

## p408-409
### TABLE 14.9 Common Alignment and Exposure Troubleshooting Problems

| Problem | Probable Cause | Corrective Action |
|---|---|---|
| **1. Excessive overlay error.*** | **A.** Incorrect alignment system measurement of reticle and wafer alignment marks | Possible measurement error sources are:<br>- Verify correct process recipe and reticle is used for a specific mask layer.<br>- Verify the calibration and stability of the alignment system to determine the position of the alignment marks.<br>- Verify calibration of alignment mark-to-pattern relationship, including thermal and/or mechanical effects.<br>- If error is within one tool, then optical distortion is probably not source of problem. If error is tool-to-tool, check difference in optical distortion of two different projection optics. |
| **1. Excessive overlay error.*** | **B.** Problem with reticle. | - Verify there is no problem with reticle mounting and/or reticle heating that could change alignment mark-to-pattern position.<br>- Check there is no particulate contamination on alignment marks that makes the alignment system incorrectly determine the mark position. |
| **1. Excessive overlay error.*** | **C.** Error in wafer or reticle stage that holds and positions wafer and reticle. | - Wafer and/or reticle stage has errors in position and rotation during exposure that contributes to overlay errors.<br>- Excessive vibration of wafer or reticle stage. Tools have built-in vibration and shock isolation.<br>- Unacceptable wafer or reticle stage heating that distorts wafer or reticle.<br>- Chucking errors that vacuum clamp wafers differently and cause wafer distortion. |
| **1. Excessive overlay error.*** | **D.** Problem with projection optics. | - Calibration error in the lens magnification adjustment causes pattern mismatches.<br>- Focus errors and/or unacceptable field flatness that causes image distortion or shifts.<br>- Unacceptable heating causes optics distortion. |
| **2. Drift in KrF laser parameters.**** | **A.** Laser properties that can change are:<br>- Laser spectral bandwidth and energy distribution.<br>- Wavelength stability.<br>- Output energy and repetition rate.<br>- Pulse-to-pulse energy stability. | All laser measurements and calibrations should be performed after specialized training by the supplier, including:<br>- Use special wavemeter to measure wavelength. Drift in wavelength affects focus at the wafer plane.<br>- Assess background optical noise levels and electronic offsets to determine impact on energy distribution.<br>- Measure bandwidth of laser output using procedure specified by supplier. |

> *G. Gallatin, "Alignment and overlay," *Microlithography, Micromachining and Microfabrication* vol. 1, ed. J. Sheats and B. Smith (New York: Marcel Dekker, 1998), p. 318.    
> **P. Das and U. Sengupta, "Krypton Fluoride Excimer Laser for Advanced Microlithography," *Microlithography Science and Technology* ed. J. Sheats and B. Smith (New York: Marcel Dekker, 1998), p. 299.

---

## p429-430
### TABLE 15.3 Key Measures at Post-Develop Inspection

| Quality Parameter | Types of Defects | Remarks |
|---|---|---|
| **1. Critical dimensions.** | A. Wider CDs than normal. | - Improper stepper focus.<br>- Not enough time or energy during exposure.<br>- Not enough develop time or weak developer solution.<br>- Incorrect process recipes during exposure or develop steps. |
| **1. Critical dimensions.** | B. Narrower CDs than normal. | - Excessive time or energy during exposure.<br>- Excessive develop time or strength of developer solution.<br>- Incorrect process recipes during exposure or develop steps. |
| **2. Contamination.** | A. Particles and foreign contamination on the resist surface. | - Equipment needs to be kept clean, with special focus on the track equipment.<br>- Inadequate cleaning and rinsing of wafers.<br>- Developer chemicals and rinse water require point-of-use filters to remove contaminants. |
| **3. Surface defects.** | A. Scratches in the resist surface. | - Wafer handling errors or tool misadjustments related to cassette indexers and robotic handling systems. |
| **3. Surface defects.** | B. Particles, spots and stains. | - Chamber exhaust flow, dispenser alignment, dispense pressure, wafer leveling, splashbacks, drips, spin speed, are all possible contributors. |
| **3. Surface defects.** | C. Missing resist, extra resist, or scumming. | - Incorrect puddle time.<br>- Incorrect dispense volume or position.<br>- Improper rinsing after the develop process.<br>- Improper or uneven baking. |
| **3. Surface defects.** | D. Striations in photoresist along the sidewalls of the resist features. | - Standing waves or reflective notches (unacceptable CD variation).<br>- Improper or no antireflective coating (ARC) was used. |
| **4. Overlay registration.** | A. Improper alignment or overlaying of one layer over a previous layer. | - This is not a problem caused by the develop process.<br>- It is more likely a stepper-induced problem.<br>- Wrong process recipe or reticle was used.<br>- Poor temperature and humidity control. |

---

## p431-432
### TABLE 15.4 Common Develop Troubleshooting Problems

| Problem | Probable Cause | Corrective Actions |
|---|---|---|
| **1. Linewidths and holes do not meet CD requirements.** | **A.** Underdeveloped or underexposed positive resist across entire wafer. | - Ensure correct stepper process recipe was used.<br>- Check for insufficient exposure time and energy settings.<br>- Check stepper illuminator system.<br>- Verify dose meter (light integrator) is functioning properly.<br>- Ensure correct recipe on developer was used.<br>- Check for insufficient puddle time and quantity settings.<br>- Check developer equipment.<br>- Check bake temperatures. |
| **1. Linewidths and holes do not meet CD requirements.** | **B.** Overdeveloped or overexposed positive resist across entire wafer. | - Ensure correct stepper process recipe was used.<br>- Check for excessive exposure time and energy settings.<br>- Check stepper illuminator system.<br>- Verify dose meter (light integrator) is functioning properly.<br>- Ensure correct recipe on developer was used.<br>- Check for excessive puddle time and quantity settings.<br>- Check developer equipment.<br>- Check bake temperatures. |
| **1. Linewidths and holes do not meet CD requirements.** | **C.** No measurable CDs. | - Check exposure or develop operation.<br>- Check reticle or process recipe.<br>- Wafer may have skipped coat, expose, post-exposure bake, or develop step.<br>- Rework wafer. |
| **2. Resist scumming.** | **A.** Resist residue remains on the wafer after the develop operation is completed. | - Check develop equipment process recipe.<br>- Verify puddle time and puddle quantity are correct.<br>- Check the rinser operation.<br>- Check bake oven times and temperatures.<br>- Rework wafer. |
| **3. Contamination and defects.** | **A.** Possible causes may include the chemicals, rinse water, and process chamber. | - Verify puddle time and puddle quantity are correct.<br>- Clean the develop process chamber, then recheck a test wafer for further contamination.<br>- Check, and if necessary, replace line filters for the developer and rinse water. |
| **3. Contamination and defects.** | **B.** Misting or backsplashing from the dispenser can cause contamination. | - Check chamber exhaust level.<br>- Check alignment of dispenser relative to the wafer.<br>- Check for drips from dispenser assembly.<br>- Rework wafer. |
| **4. Collapsing of resist pattern after develop.** | **A.** High aspect ratio (>5:1) will lead to collapsing of resist lines.* | - Verify that the resist is not excessively thick, since this will increase the aspect ratio and make the resist more likely to collapse.<br>- Check that the resist has proper adhesion to the wafer.<br>- The problem resolution may require a material or process change (e.g., more rigid resist). |
| **5. Unacceptable CD variation at top of CA DUV resist profile.** | **A.** Amine contamination of resist after exposure. | - Check integrity of environmental chamber filtering system.<br>- Check to see if coated-wafers may have been exposed to external chemical contamination.<br>- Asses whether resist is best selection for length of delay (newer resists withstand a longer time before PEB). |

> *J. Yu, et al., "Analysis of Resist Pattern Collapse and Optimization of DUV Process for Patterning Sub-0.20 mm Gate Line," *Advances in Resist Technology and Processing XV, Proceedings of SPIE*, Vol. 333, (Bellingham, WA: SPIE, 1998): p. 880.

---

# ETCH (Etch)

> 식각(16장).

## p469–470
### TABLE 16.10 Quality Measures for Etch Final Inspection

| Quality Parameter | Types of Defects | Remarks |
|---|---|---|
| **1. Critical dimension bias.** | A. Linewidth change: excessive difference between photoresist linewidth and final feature linewidth after etch. | - CD bias for linewidth change is measured by comparing pre-etch linewidth in photoresist with post-etch linewidth of the same feature on the wafer. Measurements can be done with an SEM.<br>- Excessive CD bias requires optimization of the etch process for undercutting or slope.<br>- The photoresist profile has an effect on CD bias. Vertical resist profile produces best CD bias. |
| **2. Metal corrosion.** | A. Corrosion or attack of metal film after etch. | - Corrosion often results from residual HCl on the wafer that is exposed to water vapor in the air.<br>- Corrosion may be visible as small bubbles along the side of metal lines. This defect is looked for by optical microscope or SEM. |
| **3. Sidewall contaminants after etching.** | A. Residual sidewall passivants that remain after etch, including remaining photoresist. | - Minimize formation by optimizing the pre-metal etch photoresist hard bake.<br>- Residues are usually removed by post-etch solvents or dilute buffered HF.* |
| **3. Sidewall contaminants after etching.** | B. Contaminants backsputtered onto the sidewall of the metal line or a via hole. | - Backsputtering can occur due to polymer used to passivate sidewall, leaving a "veil" residue (thin overhang along metal line or via sidewall). |
| **4. Loading effects.** | A. Microscopic nonuniformity of etch process. | - Etch rate between narrow openings is slower than open-field areas due to reduced density of reactive radicals in small space.<br>- Balance pressure and power of etch process.** |
| **5. Shorts after metal etch.** | A. Bridging of metal lines after etch leading to electrical short. | - Reduce pattern density effects from microloading. |
| **6. Excessive post-etch residue.** | A. The following types of residue may exist after etch:<br>- Stringers (small strings of residue)<br>- Veils (thin residue overhang)<br>- Crowns<br>- Rails<br>- Corrosion after metal etch | The causes of residue after etch are:<br>- Nonuniform etch process.<br>- Films deposited over topography.<br>- Nonuniform dopant distribution in film.<br>- Contaminants in the film (in addition to intentional alloys such as Cu in Si).<br>- Contaminants in gas or chamber. Check supply filters or clean system.<br>- Incorrect process parameter, such as high etch rate. |

> \* K. Mautz, *Optimization of Single Wafer and Batch Metal Etch Manufacturing Processees* vol. 96-12 (Pennington, NJ: The Electrochemical Society, 1996), p. 283.    
> \*\* S. Gonzales, J. Quijada, and G. Grivna, *Submicron Metal Etch Integration Study* vol. 2875 (Bellingham, WA: SPIE, 1996), p. 302.

---

## p470–471
### TABLE 16.11. Common Dry Etch Troubleshooting Problems

| Problem | Probable Cause | Corrective Actions |
| --- | --- | --- |
| **1. Incorrect etch rate.** | **A.** Change in RF power.<br>**B.** Incorrect temperature.<br>**C.** Problem with pressure.<br>**D.** Endpoint detection not functioning properly.<br>**E.** Improper wafer spacing.<br>**F.** Improper gas-flow dynamics.<br>**G.** Improper maintenance.<br>**H.** Incorrect process recipe. | - Check and troubleshoot RF generator and matching unit.<br>- Check backside wafer cooling system.<br>- Calibrate vacuum gauges (e.g., capacitive manometer) and pressure control system.<br>- Check endpoint detection system.<br>- Check wafer-to-electrode gap.<br>- Verify gas distribution system.<br>- Perform chamber wet clean.<br>- Verify process recipe and parameters. |
| **2. Inadequate selectivity.** | **A.** Etch rate too high.<br>**B.** Improper gas flow or pressure.<br>**C.** Endpoint detection problem.<br>**D.** Wrong wafer temperature.<br>**E.** Incorrect process recipe. | - Verify etch rate.<br>- Calibrate MFCs and vacuum gauges.<br>- Check/calibrate endpoint detection.<br>- Check wafer cooling system.<br>- Confirm process recipe and parameters. |
| **3. Improper sidewall profile angle.** | **A.** Contamination on sidewall.<br>**B.** Temperature of wafer.<br>**C.** System pressure.<br>**D.** Incorrect process recipe (misprocess). | - Check for polymer buildup in chamber.<br>- Backside contamination of wafer causing nonuniform heating.<br>- Check/calibrate MFCs and perform leak test to check for contamination. |
| **4. Etch nonuniformity across wafer.** | **A.** Depletion of etchant gas concentration due to ARDE.<br>**B.** Improper gas flow.<br>**C.** Temperature of wafer.<br>**D.** Improperly positioned wafer in chamber.<br>**E.** Chamber configuration.<br>**F.** Improper film thickness.<br>**G.** Improper maintenance. | - Verify acceptable design for dense and nondense areas of wafer.<br>- Check/calibrate gas distribution system.<br>- Check thermocouples and wafer cooling.<br>- Check robotics, wafer handling system, and vacuum chuck.<br>- Check reactor plate spacing.<br>- Measure and verify film thickness.<br>- Perform chamber wet clean. |
| **5. Plasma damage.** | **A.** Nonuniform plasma.<br>**B.** Excessive ion bombardment of gate oxide.<br>**C.** Excessive RF power.<br>**D.** Improper maintenance. | - Poorly designed or maintained plasma equipment.<br>- Suboptimum process conditions.<br>- Check recipe and RF generator. |
| **6. Particle Contamination.** | **A.** Leak/contamination from gas lines.<br>**B.** Tool operation.<br>**C.** Improper gas chemistry. | - Leaks or faulty MFCs.<br>- Improper tool shutdown, operation, or maintenance.<br>- Wrong process recipe.<br>- Perform wet clean. |
| **7. Metal Corrosion.** | **A.** Moisture.<br>**B.** Gas flow.<br>**C.** Contaminants from etch process.<br>**D.** Wrong maintenance procedure. | - Excessive time delay for post-etch residue cleanup.<br>- Check MFCs for correct process gases.<br>- Control time to resist strip.<br>- Check maintenance procedure. |

---

# CMP

> CMP(18장). 한국어판 페이지.

## p661
### 표 18-6 CMP의 품질 측정
| 품질 매개변수 | 결함의 형태 | 설명 |
|---|---|---|
| 1. 웨이퍼 표면의 긁힘과 둥근 홀들 | A. 내부 금속 단락(금속층과 금속층) | 미세흠집들은 정밀조사에서 찾아내기가 극도로 힘들다.<br>가능한 원인:<br>- 슬러리 안으로 확산되는 입자 크기의 빈약한 제어<br>- 오랜 축적과 부적절한 사용은 슬러리 입자의 건조를 야기하고, 더 큰 입자 만들게 한다.<br>- 슬러리에서의 입자오염<br>- 미세흠집을 줄이기 위한 이차 완충 작용의 결핍 혹은 최적화되지 않았음 |
| 2. Dishing<br>(사발 모양으로 움푹 들어가는 것) | A. 높은 연마 비율 물질에서의 침하(지반의 함몰) | - dishing은 전형적으로 낮은 연마 비율의 환경(예, 연마 정지층으로 사용되는 질화물) 안에 있는 높은 연마 비율 물질들(예, 산화 STI)에서 발생한다.<br>- 높은 연마 비율 물질이 보다 큰 표면적을 가졌을 때 더 많은 dishing이 발생한다.<br>- PAD의 단단함의 증가는 dishing을 줄일 것이다(PAD는 덜 깊숙한 곳에서 구부러진다).<br>- 임시방편으로서 얼마간의 디자이너들은 큰 것 안에서 dishing을 막기 위해 버팀 PAD로써 견본을 사용한다(예, bonding pads). 이것은 표면이 이용 가능할 때만 이용된다.<br>- 구리(Cu)에서, hard pad와 높은 화학적 제거도를 갖는 슬러리와의 결합(오로지 높은 구역에서만)은 dishing을 최소화할 것이다. |
| 3. 부식(침식) | A. 낮은 연마 비율 물질에서 침하 또는 과도한 제거 | - 낮은 연마 비율 물질(예, 질화물)의 부식<br>- 그것은 금속 패턴 밀도가 질화물 차폐와 텅스텐을 상호 연결할 때와 같이 증가할 때 두드러진다.<br>- 비아 식각이 하부 금속층과 연결되지 않을 때 불완전한 비아 시각을 야기시킬 수 있다.<br>- 일반 압축성과 최적 조건의 슬러리 이동을 위해 조정할 수 있는 연마 패드들을 연구하라. |
| 4. 잔류물(찌꺼기) | A. 모서리를 따라서 스트링거의 구성에서의 잔류물 | CMP는 상대적인 세정 공정이다(RIE etch back 공정과 비교될 때). 적절히 수행된 CMP는 특정한 모서리를 따라서 스트링거들을 줄일 것이다. 스트링거들은 단락을 야기시키거나 칩의 신뢰성을 감하시킨다. 스트링거들의 가능한 요인과 작용들:<br>- 스트링거들은 텅스텐과 폴리실리콘 stringer와 같은 다른 물질들에서 발생한다.<br>- 연마 패드와 슬러리 화학물질 등을 최대한 활용해서 다른 물질들 사이에서 더 많은 단일화된 연마를 이루어서 스트링거들을 최소화하라. |

---

## p662
### 표 18-7 CMP 고장진단 문제

| 문제점 | 발생 원인 | 해결방법 |
|---|---|---|
| 1. 슬러리 안의 과도하게 큰 입자들 | A. 슬러리가 디스펜서 측벽의 내부에서 건조되고, 슬러리 혼합물 안으로 떨어진다.<br>B. 입력 슬러리에서의 마찰 입자의 럼핑<br>C. 공급업자에 의해서 제공되는 불량 슬러리 | - POU 필터 여과법을 슬러리에 사용해라.<br>- 슬러리의 제조와 납품을 최적화하라.<br>- 계면활성제와 안정제로 슬러리의 안정성을 향상시켜라. |
| 2. 웨이퍼 표면의 불균일한 연마 | A. 중심을 빠르게(중심을 웨이퍼의 다른 지역보다 빠르게 연마하라).<br>B. 중심을 느리게(중심을 웨이퍼의 다른 지역보다 느리게 연마하라). | - 플래튼 위의 부적절한 패드 외형은 중심을 빠르게 또는 느리게 하거나, 가장자리 문제들을 야기할 수 있다. 과도하게 패드가 닳았는지 검사하라.<br>- 웨이퍼 캐리어(wafer carrier) 위의 압력(아래 방향 압력)이 잘못 설정되어 있다.<br>- 패드 콘디션 암(arm)이 적절하게 적용되었는지 또는 닳았는지(glazing 안 된 상태) 검사하라.<br>- 부족한 슬러리 흐름률 또는 잘못된 점성률(흐르는 정도).<br>- 웨이퍼 캐리어에서 후면막의 악화는 웨이퍼가 납작하게 펼쳐지지 않게 야기한다.<br>- 테이블의 회전 속도가 잘못 설정되어 있다.<br>- 웨이퍼의 뒤쪽 압력이 잘못 설정되어 있다. |
| 3. 구리 CMP 후에 깨끗한 웨이퍼의 입자들 | A. 웨이퍼에서 과도한 입자들의 발견(0.18 μm CD에서 요구되는 것은 0.08 μm 크기에서 웨이퍼당 결함들이 20 미만이다).<br>B. 광 직렬 자국들과 bond 패드 지역들과 같이 깊은 특성들 안에서 잔여의 슬러리의 생성.<br>C. 유전체 또는 패턴화된 웨이퍼들의 line들 사이로부터 잔여 구리의 제거 | CMP의 주된 관심은 세정후의 표면에서의 입자들의 레벨이다. 가능한 해결 방법들:<br>- 잔여 구리의 세정이 패턴화된 웨이퍼에서 끝났는지 아닌지를 조사하라.<br>- 양쪽 브러시 솔(수세미)에서 브러시가 적재되고 있는지 검사하라(오염).<br>- 특히 구리 잔여물에 최적의 세정 화학제가 사용되었는지 확인하라.<br>- 웨이퍼 표면에 다른 물질을 노출시키는 것부터 브러시와 세정 화학물질까지 화학적으로 역 오염이 없다는 것을 확신하라. |
| 4. 연마 패드의 윤내기 | A. 부적절하게 적용된 검사용 암<br>B. 과도하게 닳은 패드 | 패드 시운전과 검사는 일관된 연마 수행을 위해 필요하다.<br>윤내기 문제 해결들:<br>- 적절한 패드 시운전이 수행되었는지 확인하라(예, 생산 웨이퍼를 가동하기에 앞서 견본 웨이퍼를 가동하라).<br>- 하향압력 조사를 적용하거나 검사 표면을 바꿔라.<br>- 연마패드를 교체하라. |

---

# CLEAN (Cleaning)

> 세정·오염 제어(6장, 원서 p114–142). 6장엔 완성된 Troubleshooting 표가 없어 서술을 형제 표와 동일한 `Problem | Probable Cause | Corrective Action` 형식으로 재구성.
> ⚠️ 프로버넌스 주의: 2행 대책의 "CO 라인 Ni 접액부 회피 · 부동태화/전해연마 SUS · POU 정제기"는 원문 p116(Ni+CO→니켈 카보닐)의 귀결 + 웹 검증 보강분(부동태화 기전). 6행 원인 B의 "NH₄OH 과잉→에칭" 기전은 APM 표준 도메인 지식(원문 p136은 금속오염만 명시).

## p114–142 (Ch.6 Contamination Control — reconstructed)

### TABLE 6.R Troubleshooting for Wafer Contamination & Cleaning (reconstructed from Ch.6 prose)

| Problem | Probable Cause | Corrective Action |
| --- | --- | --- |
| **1. Particle contamination on the wafer surface.** (Open/bridged circuits, shorts between adjacent conductors; killer defect when particle > ½ minimum feature size.) | A. Airborne aerosols in fab air; objects/personnel disrupting laminar flow re-suspend particles.<br>B. Human-generated particles — skin, hair, clothing lint (greatest source in a manned area).<br>C. Production equipment — chamber-wall by-product flaking, wafer handling, mechanical motion, pump/vent (single most significant particle source).<br>D. Suspended particulates / silica in DI water and process chemicals. | - Supply air through ceiling HEPA/ULPA filters with vertical laminar flow at slight positive pressure; hold cleanroom class for the feature size (bay-and-chase: class 1 process bay / class 1,000 service chase; air turnover ~6 s).<br>- Isolate facility equipment (pumps, piping, ductwork) in the sub-fab; exhaust heat/chemicals from tools.<br>- Enforce cleanroom garments (bunny suit) + protocol; minimize personnel movement.<br>- SC-1 (APM) wet clean removes particles via oxidation, slight surface etch, and zeta-potential–driven electrostatic repulsion; add megasonic energy for sub-micron particles.<br>- PVA brush scrubbing (esp. after CMP); point-of-use membrane filtration of chemicals/water. |
| **2. Metallic impurity / mobile ionic contamination (MIC).** (Increased pn-junction leakage, reduced minority-carrier lifetime, gate-oxide/poly structural defects, Vt shift; latent in-field failures.) | A. Alkali metals (Na, K, Li — mobile ionic contaminants) & other metal impurities (Fe, Cu, Cr, W, Al, Ti) from chemicals and process steps (ion implantation highest).<br>B. Humans as Na carriers (saliva, perspiration).<br>C. Gas–piping reaction (e.g., CO + Ni → nickel-carbonyl particles).<br>D. Dissolved ions in water (Na⁺, K⁺). | - SC-2 (HPM) wet clean ionizes and dissolves metals; piranha (SPM), primarily organics/PR strip, also removes some metals.<br>- Add a chelating agent (e.g., EDTA) to the clean bath to prevent metal redeposition.<br>- Ozonized UPW + SC-2 for Cu/Ag removal; use high-assay chemicals; on CO-bearing gas lines avoid nickel-wetted parts (nickel-carbonyl risk) — use passivated/electropolished stainless steel and point-of-use purifiers. |
| **3. Organic contamination.** (Degrades gate-oxide integrity under certain conditions; blocks cleaning so metals remain on the surface.) | A. Bacteria, lubricants, vapors, detergents, solvents, moisture.<br>B. Total organic carbon (TOC) dissolved in DI water. | - SC-1 (APM) and piranha (SPM) remove organics.<br>- Use oil-free (lubricant-free) pumps/bearings; control TOC in DI water.<br>- Ozone-injected UPW as a light-organic clean option. |
| **4. Native oxide on the silicon surface.** (Interferes with epi / ultrathin gate-oxide growth; raises contact resistance at W-plug/doped-Si contacts; traps metallic impurities.) | A. Exposure of Si to air (adsorbed moisture + room O₂) at room temperature.<br>B. Exposure to DI water containing dissolved oxygen. | - Strip with DHF or BHF (HF-last step); H-terminated surface resists reoxidation.<br>- Use integrated high-vacuum multichamber tools to avoid air/moisture exposure.<br>- Control dissolved oxygen in DI water. |
| **5. Electrostatic discharge (ESD).** (Vaporizes metal lines / punches through oxide; gate-oxide breakdown; charged wafer attracts & polarizes particles.) | A. Triboelectric charging — contact/rubbing of dissimilar materials.<br>B. Low humidity promotes static-charge buildup; the fab holds ~40% RH as a static-vs-corrosion compromise (raising RH cuts static but increases corrosion).<br>C. Insulating films on the wafer (e.g., oxide) hold charge. | - Use static-dissipative cleanroom materials + continuous grounding of people/objects.<br>- Neutralize insulator charge with air ionization (emitter or soft-X-ray).<br>- ESD-safe garments; control RH (trade-off against corrosion). |
| **6. Cleaning-induced damage / residue** *(side effects of the clean itself)*. (Thin-oxide growth difficulty, recontamination, watermark/particle defects.) | A. SC-1 over-etch → silicon microroughening.<br>B. H₂O₂ depletion in aged SC-1 bath → relative NH₄OH excess intensifies Si etch/microroughening (cf. A); separately, dissolved metals redeposit on the wafer; overall composition drift.<br>C. Hot DI rinse → surface microroughness; incomplete drying → watermarks on hydrophobic (HF-last) surfaces. | - Replace baths frequently; adopt dilute chemistries and point-of-use chemical generation.<br>- Dry adequately: spin dryer with static eliminator, or IPA vapor dry.<br>- Monitor rinse-water resistivity to confirm chemical removal. |
