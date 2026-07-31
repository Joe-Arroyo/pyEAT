# Tutorial
## **File formats:**
pyEAT reads raw data files directly from the instrument software or from exported files, it handles the parsing automatically for each tab. 
- GAMRY (.DTA): file exported directly from Gamry Framework during the experiment. The Gamry parser reads the file directly with no need for external libraries or dependencies. According to the experiment, the data used by pyEAT:

| Column | Description |
|---|---|
| `T` | Time (seconds) |
| `Vf` | Voltage vs. reference (V) |
| `Im` | Current (A) |
| `Freq` | Frequency (Hz) — EIS only |
| `Zreal` | Real impedance (Ω) — EIS only |
| `Zimag` | Imaginary impedance (Ω) — EIS only |

- pyEAT supports both US (.) and European (,) decimal formats automatically
   
- AUTOLAB (.xlsx, .txt): pyEAT does not open .NOX files so it reads exported files from the Autolab NOVA Software with semicolon-separated (;) columns with comma as decimal separator. One header row with column names and data below.

For EIS:

| Column | Description |
|---|---|
| `Frequency` | Frequency (Hz) |
| `Z'` | Real impedance (Ω) |
| `-Z''` | Negative imaginary impedance (Ω) |

Note: Autolab exports -Z'' (negative imaginary). pyEAT automatically negates it internally to follow the standard convention.

For polarization curves and chronopotentiometry it uses the same parser and read the same data:

| Column | Description |
|---|---|
| `Time (s)` | Time (seconds) |
| `WE(1).Potential (V)` | Voltage vs. reference (V) |
| `WE(1).Current (A)` | Current (A) |


- The parser tries both tab (\t) and semicolon (;) separators automatically
- Column names are matched by keyword, not exact name — so minor variations in NOVA's export format are handled and no particular order for the columns in the datafile.
   
- RIDEN (.xlsx): this file comes from the Riden power supplies (RD 6006 for our case) as an standard exce; file.

| Column | Description |
|---|---|
| `Read Time` | Timestamp (HH:MM:SS) |
| `Output Voltage` | Voltage (V) |
| `Output Current` | Current (A) |

- Only supported for chronopotentiometry and polarization curves — not EIS
- One .xlsx file can contain a full multi-step chronopotentiometry experiment
- Parser matches by keywords not by column order
- **Caution:** some stored values are stored as text and will not work with pyEAT. Convert these values into numbers in Excel or similar, here is an example:

<img width="521" height="239" alt="image" src="https://github.com/user-attachments/assets/337467d8-566f-45ad-b50a-d09bdbb02420" />

- Custom CSV (.txt): designed for custom powwer supplies, this is the most strict format since it takes the values from column order, no keywords.

| Position | Column | Description |
|---|---|---|
| 1 | `voltage` | Voltage (V) |
| 2 | `current` | Current (A) |
| 3 | `power` | Power (W) |
| 4 | `timestamp` | Date and time (`DD/MM/YYYY HH:MM:SS`) |

- No header row — the first line must be data
- Comma-separated
- Timestamp format must be exactly DD/MM/YYYY HH:MM:SS
- Only supported for chronopotentiometry and polarization curves — not EIS

**Future versions will be more flexible in terms of column order and time format**


## **How to use pyEAT**

### 1. EIS tab
<img width="3779" height="1904" alt="image" src="https://github.com/user-attachments/assets/0161bd11-182e-4796-b136-4a2ef725fc32" />

### 2. Polarization curve tab: 
Polarization curves can be build from single or multiple files, for this:

#### 2.1 Create a New Group which will contain one or more curves.

#### 2.2 Create a New Curve by loading either one file or a folder with multiple files. Remember to select the right instrument before loading the data

After loading, each group will be plotted with is unique color and each curve within will be plotted using shades of such color. Here, we plotted data from a decommissioned PEM electrolyzer obtained with Autolab (data from a single file) and Gamry (data from a folder with multiple datafiles) potensiostats:
<img width="3804" height="1948" alt="image" src="https://github.com/user-attachments/assets/641181d0-46bb-4222-9e1d-9eda903737f0" />

The curves of a group can be averaged:

<img width="2575" height="1707" alt="image" src="https://github.com/user-attachments/assets/3ce5a65a-6b66-461d-848a-a4bc3bc9914a" />

When there is average curve present, the transient curves are not shown.

The data from polarization and transient curves can be exported as CSV files:

<img width="412" height="426" alt="image" src="https://github.com/user-attachments/assets/5bb5f71a-dd79-4dda-97e2-2f8d13707f4a" />

The exported file will look like this:

<img width="1062" height="1626" alt="image" src="https://github.com/user-attachments/assets/aacf0b59-4351-4a8c-a904-1c90e5ecf845" />

### 3. Chronopotentiometry tab
<img width="3780" height="1944" alt="image" src="https://github.com/user-attachments/assets/62b902c2-ba3e-49bb-aee9-1e261b2879ee" />

In this tab, the data is presented as V vs t and I vs t curves, and the axis limits can be ajusted for a better presentation.

---
### Side note: construction of a polarization curve from chronopotentiometric data
According to the *EU harmonised polarisation curve test method for low-temperature water electrolysis* (you can find it [here](https://publications.jrc.ec.europa.eu/repository/handle/JRC104045)), a polarization curve is the plot of the voltage or power density vs the current or current (*I*) density (*j*) of the cell/stack., and it can be obtained by:

a. Linear current sweep at an a specified rate (80 mA/cm<sup>2</sup> per minute for PEM and 16 mA/cm<sup>2</sup> per minute for AWE or AEMWE)

b. Stepwise steady-step current sweep, i.e, applying consecutive current steps

pyEAT currently works only with data from current sweeps under galvanostatic control.

Here´s an example:

<img width="2599" height="899" alt="image" src="https://github.com/user-attachments/assets/353666e0-641b-40f8-b86b-c95c2a4b8c2d" />
In pyEAT, the transient is avaiable in the plot options by selecting the plot type.

The curve will show the average voltage calculated at the steady stage, which is by default the last 30 s of each galvanostatic step:

<img width="2640" height="906" alt="image" src="https://github.com/user-attachments/assets/a1c7af5f-b4ae-4eec-8de7-3d2800a70127" />

Finally, the average voltage is plotted against the current density. In the polarization curve tab, this is the default plot:

<img width="3426" height="1871" alt="image" src="https://github.com/user-attachments/assets/b50e8bcd-9be5-40f6-9918-7b79643d5a05" />

#### Remarks:
a. By default, pyEAT uses the last 30 s of the measurement to calculate the average voltage and an electrode area of 1 cm<sup>2</sup>. Both parameters can be changed in the processing parameters mene, these parameters can be applied to a single curve(s) and group(s). When the electrode area is 0 cm<sup>2</sup>, the x-axis changes current.
   
b. The polarization curves will have error bars, which are calculated the statistical tratment of the EU harmonised polarisation curve test method for low-temperature water electrolysis.

#### Single curve: standard error per point

Each point of a polarization curve is obtained from the steady-state region of
one current step. For step $k$, the last $t_{avg}$ seconds of the step are used
(or the full step if it is shorter), giving $M$ voltage samples $U_{k,l}$.

The reported voltage is the sample mean:

$$U_{k,avg} = \frac{1}{M}\sum_{l=0}^{M-1} U_{k,l}$$

with sample standard deviation (Bessel-corrected, $M-1$):

$$U_{k,std} = \sqrt{\frac{1}{M-1}\sum_{l=0}^{M-1}\left(U_{k,l}-U_{k,avg}\right)^2}$$

The uncertainty assigned to the point is the **standard error of the mean**:

$$U_{k,sterr} = \frac{U_{k,std}}{\sqrt{M}}$$

The standard error is used (rather than the standard deviation) because it
quantifies how well the steady-state mean is determined and remains comparable
between points with different numbers of samples $M$ — e.g. when a step is
shorter than the averaging window. This value is drawn as the error bar and
exported in the `V_uncertainty` column.

#### Multiple curves: standard deviation of the average

When $N$ replicate curves within a group are averaged (*Average Curves*), the
voltage of each averaged point $k$ is the mean over the replicates:

$$\bar{U}_k = \frac{1}{N}\sum_{i=1}^{N} U_k^{i}$$

and its uncertainty is the **sample standard deviation across curves**
(Bessel-corrected, $N-1$):

$$s_k = \sqrt{\frac{1}{N-1}\sum_{i=1}^{N}\left(U_k^{i}-\bar{U}_k\right)^2}$$

Here the standard deviation is reported instead of the standard error: it
describes the experiment-to-experiment reproducibility of the measurement,
which is the quantity of interest when comparing replicate runs.

In summary:

| Case | Uncertainty reported | Meaning |
|---|---|---|
| Single curve | $U_{k,std}/\sqrt{M}$ | Precision of the steady-state mean (within-step) |
| Averaged curves | $s_k$ over $N$ curves | Reproducibility between replicate curves |





