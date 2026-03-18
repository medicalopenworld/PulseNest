//////////////////////////////////////////////////////////////////////////////////////////
//
//    Arduino library for the AFE44XX Pulse Oxiometer Shield
//
//    This software is licensed under the MIT License(http://opensource.org/licenses/MIT).
//
//   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
//   NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
//   IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
//   WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
//   SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
//
//   For information on how to use, visit https://github.com/Protocentral/AFE44XX_Oximeter
/////////////////////////////////////////////////////////////////////////////////////////



#include "protocentral_afe44xx.h"
#include "Protocentral_spo2_algorithm.h"
#include "protocentral_hr_algorithm.h"

#define AFE44XX_SPI_SPEED 2000000
SPISettings SPI_SETTINGS(AFE44XX_SPI_SPEED, MSBFIRST, SPI_MODE0); 

volatile boolean afe44xx_data_ready = false;
volatile int8_t n_buffer_count; //data length

int dec=0;

unsigned long IRtemp,REDtemp;

int32_t n_spo2;  //SPO2 value
int32_t n_heart_rate; //heart rate value

uint16_t aun_ir_buffer[100]; //infrared LED sensor data
uint16_t aun_red_buffer[100];  //red LED sensor data

int8_t ch_spo2_valid;  //indicator to show if the SPO2 calculation is valid
int8_t  ch_hr_valid;  //indicator to show if the heart rate calculation is valid

const uint8_t uch_spo2_table[184]={ 95, 95, 95, 96, 96, 96, 97, 97, 97, 97, 97, 98, 98, 98, 98, 98, 99, 99, 99, 99,
                                    99, 99, 99, 99, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100,
                                   100, 100, 100, 100, 99, 99, 99, 99, 99, 99, 99, 99, 98, 98, 98, 98, 98, 98, 97, 97,
                                    97, 97, 96, 96, 96, 96, 95, 95, 95, 94, 94, 94, 93, 93, 93, 92, 92, 92, 91, 91,
                                    90, 90, 89, 89, 89, 88, 88, 87, 87, 86, 86, 85, 85, 84, 84, 83, 82, 82, 81, 81,
                                    80, 80, 79, 78, 78, 77, 76, 76, 75, 74, 74, 73, 72, 72, 71, 70, 69, 69, 68, 67,
                                    66, 66, 65, 64, 63, 62, 62, 61, 60, 59, 58, 57, 56, 56, 55, 54, 53, 52, 51, 50,
                                    49, 48, 47, 46, 45, 44, 43, 42, 41, 40, 39, 38, 37, 36, 35, 34, 33, 31, 30, 29,
                                    28, 27, 26, 25, 23, 22, 21, 20, 19, 17, 16, 15, 14, 12, 11, 10, 9, 7, 6, 5,
                                    3,   2,  1  } ;

spo2_algorithm Spo2;
hr_algo hral;

AFE44XX::AFE44XX(int cs_pin, int pwdn_pin)
{
    _cs_pin=cs_pin;
    
    _pwdn_pin=pwdn_pin;

    pinMode(_cs_pin, OUTPUT);
    digitalWrite(_cs_pin,HIGH);

    pinMode (_pwdn_pin,OUTPUT);

    hral.initStatHRM(500);
    
    /*pinMode (_drdy_pin,INPUT);// data ready

    digitalWrite(_pwdn_pin, LOW);
    delay(500);
    digitalWrite(_pwdn_pin, HIGH);
    delay(500);
    */
}

boolean AFE44XX::get_AFE44XX_Data(afe44xx_data *afe44xx_raw_data)
{
  afe44xxWrite(CONTROL0, 0x000001); // [bit0=SPI_READ=1] enable SPI read mode before first register read
  IRtemp = afe44xxRead(LED1VAL);
  //afe44xxWrite(CONTROL0, 0x000001); // ACM: en lecturas consecutivas parece que no hace falta activar el bit SPI_READ de CONTROL0
  REDtemp = afe44xxRead(LED2VAL);

  // ACM: additional readings for ambient light subtraction
  unsigned long ambientIRtemp = afe44xxRead(ALED1VAL);            // ambient measured after IR measurement
  unsigned long ambientREDtemp = afe44xxRead(ALED2VAL);           // ambient measured after RED measurement
  unsigned long IRminusAmbienttemp = afe44xxRead(LED1ABSVAL);     // LED1-ALED1VAL
  unsigned long REDminusAmbienttemp = afe44xxRead(LED2ABSVAL);    // LED2-ALED2VAL
  afe44xx_raw_data->ambientIR_data = (signed long) ((((int32_t)(ambientIRtemp)) << 10) >> 10);
  afe44xx_raw_data->ambientRED_data = (signed long) ((((int32_t)(ambientREDtemp)) << 10) >> 10);
  afe44xx_raw_data->IRminusAmbient_data = (signed long) ((((int32_t)(IRminusAmbienttemp)) << 10) >> 10);
  afe44xx_raw_data->REDminusAmbient_data = (signed long) ((((int32_t)(REDminusAmbienttemp)) << 10) >> 10);

  afe44xx_data_ready = true;
  IRtemp = (unsigned long) (IRtemp << 10);
  afe44xx_raw_data->IR_data = (signed long) (IRtemp);
  afe44xx_raw_data->IR_data = (signed long) ((afe44xx_raw_data->IR_data) >> 10);
  
  REDtemp = (unsigned long) (REDtemp << 10);
  afe44xx_raw_data->RED_data = (signed long) (REDtemp);
  afe44xx_raw_data->RED_data = (signed long) ((afe44xx_raw_data->RED_data) >> 10);

  // Band Pass Filter (0.5Hz - 20Hz @ 500Hz) - 2nd Order total
  apply_bandpass_filter(afe44xx_raw_data);

  if (dec == 20)
  {
    aun_ir_buffer[n_buffer_count] = (uint16_t) ((afe44xx_raw_data->IR_data) >> 4);
    aun_red_buffer[n_buffer_count] = (uint16_t) ((afe44xx_raw_data->RED_data) >> 4);
    n_buffer_count++;
    dec = 0;
  }

  dec++;

  if (n_buffer_count > 99)
  {
    Spo2.estimate_spo2(aun_ir_buffer, 100, aun_red_buffer, &n_spo2, &ch_spo2_valid, &n_heart_rate, &ch_hr_valid);
    afe44xx_raw_data->spo2 = n_spo2;
    //afe44xx_raw_data->heart_rate = n_heart_rate;
    n_buffer_count = 0;
    afe44xx_raw_data->buffer_count_overflow = true;
  }

  hral.statHRMAlgo(afe44xx_raw_data->IR_filtered_data);
  afe44xx_raw_data->heart_rate = hral.HeartRate;

  afe44xx_data_ready = false;
  return true;
}

void AFE44XX::afe44xx_init()
{
  // Reset filter states
  ir_filter_state = {0, 0};
  red_filter_state = {0, 0};

  digitalWrite(_pwdn_pin, LOW);
  delay(500);
  digitalWrite(_pwdn_pin, HIGH);
  delay(500);

  // --- Control & analog front-end configuration ---
  afe44xxWrite(CONTROL0, 0x000000); // [bit3=SW_RST=0, bit0=SPI_READ=0] normal write mode, no reset
  afe44xxWrite(CONTROL0, 0x000008); // [bit3=SW_RST=1] software reset (self-clears)

  // TIA gain stage (LED phase): CF=5pF (bits[5:3]=000), RF=500kΩ (bits[2:0]=000)
  afe44xxWrite(TIAGAIN, 0x000000);

  // TIA gain stage (ambient phase): RF_AMB=250kΩ (bits[2:0]=001), CF_AMB=5pF (bits[5:3]=000)
  afe44xxWrite(TIA_AMB_GAIN, 0x000001);

  // LED current: LED2(RED) = 0x14 = 20 steps, LED1(IR) = 0x14 = 20 steps
  // With LEDRANGE=0 (50mA full scale, 256 steps) → ~3.9mA per LED
  afe44xxWrite(LEDCNTRL, 0x001414);

  // [bit17=LEDRANGE=0] LED current range 0–50mA; all other features (XTAL, TX_REF, DYNAMIC_PWRDWN) disabled
  afe44xxWrite(CONTROL2, 0x000000);

  // [bit16=TIMEREN=1] internal timers enabled; bits[7:0]=0x07 NUMAV=7; bits[15:8]=0x07
  afe44xxWrite(CONTROL1, 0x010707);

  // --- Timing configuration (clock = 4 MHz → 1 count = 0.25 µs; PRF = 500 Hz) ---
  // Period: 7999 + 1 = 8000 counts = 2000 µs
  afe44xxWrite(PRPCOUNT, 0X001F3F); // 7999

  // --- Phase 3 (1500–2000 µs): LED2 (RED) lit ---
  afe44xxWrite(LED2STC,      0X001770); //  6000 → sample window start  = 1500.00 µs
  afe44xxWrite(LED2ENDC,     0X001F3E); //  7998 → sample window end    = 1999.50 µs
  afe44xxWrite(LED2LEDSTC,   0X001770); //  6000 → LED2 pulse start     = 1500.00 µs
  afe44xxWrite(LED2LEDENDC,  0X001F3F); //  7999 → LED2 pulse end       = 1999.75 µs

  // --- Phase 0 (0–500 µs): LED2 ambient (no LED) ---
  afe44xxWrite(ALED2STC,     0X000000); //     0 → ambient sample start =    0.00 µs
  afe44xxWrite(ALED2ENDC,    0X0007CE); //  1998 → ambient sample end   =  499.50 µs

  // ADC conversion windows (LED2 and ALED2)
  afe44xxWrite(LED2CONVST,   0X000002); //     2 → LED2 conv start      =    0.50 µs
  afe44xxWrite(LED2CONVEND,  0X0007CF); //  1999 → LED2 conv end        =  499.75 µs
  afe44xxWrite(ALED2CONVST,  0X0007D2); //  2002 → ALED2 conv start     =  500.50 µs
  afe44xxWrite(ALED2CONVEND, 0X000F9F); //  3999 → ALED2 conv end       =  999.75 µs

  // --- Phase 1 (500–1000 µs): LED1 (IR) lit ---
  afe44xxWrite(LED1STC,      0X0007D0); //  2000 → sample window start  =  500.00 µs
  afe44xxWrite(LED1ENDC,     0X000F9E); //  3998 → sample window end    =  999.50 µs
  afe44xxWrite(LED1LEDSTC,   0X0007D0); //  2000 → LED1 pulse start     =  500.00 µs
  afe44xxWrite(LED1LEDENDC,  0X000F9F); //  3999 → LED1 pulse end       =  999.75 µs

  // --- Phase 2 (1000–1500 µs): LED1 ambient (no LED) ---
  afe44xxWrite(ALED1STC,     0X000FA0); //  4000 → ambient sample start = 1000.00 µs
  afe44xxWrite(ALED1ENDC,    0X00176E); //  5998 → ambient sample end   = 1499.50 µs

  // ADC conversion windows (LED1 and ALED1)
  afe44xxWrite(LED1CONVST,   0X000FA2); //  4002 → LED1 conv start      = 1000.50 µs
  afe44xxWrite(LED1CONVEND,  0X00176F); //  5999 → LED1 conv end        = 1499.75 µs
  afe44xxWrite(ALED1CONVST,  0X001772); //  6002 → ALED1 conv start     = 1500.50 µs
  afe44xxWrite(ALED1CONVEND, 0X001F3F); //  7999 → ALED1 conv end       = 1999.75 µs

  // --- ADC reset pulses (one per phase, coincide with phase transition; start=end → minimum pulse width) ---
  afe44xxWrite(ADCRSTCNT0,   0X000000); //     0 → ADC reset phase 0 start =    0.00 µs
  afe44xxWrite(ADCRSTENDCT0, 0X000000); //     0 → ADC reset phase 0 end   =    0.00 µs
  afe44xxWrite(ADCRSTCNT1,   0X0007D0); //  2000 → ADC reset phase 1 start =  500.00 µs
  afe44xxWrite(ADCRSTENDCT1, 0X0007D0); //  2000 → ADC reset phase 1 end   =  500.00 µs
  afe44xxWrite(ADCRSTCNT2,   0X000FA0); //  4000 → ADC reset phase 2 start = 1000.00 µs
  afe44xxWrite(ADCRSTENDCT2, 0X000FA0); //  4000 → ADC reset phase 2 end   = 1000.00 µs
  afe44xxWrite(ADCRSTCNT3,   0X001770); //  6000 → ADC reset phase 3 start = 1500.00 µs
  afe44xxWrite(ADCRSTENDCT3, 0X001770); //  6000 → ADC reset phase 3 end   = 1500.00 µs
  delay(1000);
}

void AFE44XX :: afe44xxWrite (uint8_t address, uint32_t data)
{
  SPI.beginTransaction(SPI_SETTINGS);
  digitalWrite (_cs_pin, LOW); // enable device
  SPI.transfer (address); // send address to device
  SPI.transfer ((data >> 16) & 0xFF); // write top 8 bits
  SPI.transfer ((data >> 8) & 0xFF); // write middle 8 bits
  SPI.transfer (data & 0xFF); // write bottom 8 bits
  digitalWrite (_cs_pin, HIGH); // disable device
  SPI.endTransaction();
}

unsigned long AFE44XX :: afe44xxRead (uint8_t address)
{
  unsigned long data = 0;

  SPI.beginTransaction(SPI_SETTINGS);
  digitalWrite (_cs_pin, LOW); // enable device
  SPI.transfer (address); // send address to device
  data |= ((unsigned long)SPI.transfer (0) << 16); // read top 8 bits data
  data |= ((unsigned long)SPI.transfer (0) << 8); // read middle 8 bits  data
  data |= SPI.transfer (0); // read bottom 8 bits data
  digitalWrite (_cs_pin, HIGH); // disable device
  SPI.endTransaction();

  return data; // return with 24 bits of read data
}

// 2nd order Butterworth Band-pass (0.5 - 20 Hz @ 500 Hz)
// Total 2nd order (1 section) with B coefficients that sum to zero to remove DC component
static const float BP_B0 = 0.10963818f;
static const float BP_B1 = 0.0f;
static const float BP_B2 = -0.10963818f;
static const float BP_A1 = -1.77931075f;
static const float BP_A2 = 0.78072364f;

float AFE44XX::step_biquad(float x, const float b0, const float b1, const float b2, const float a1, const float a2, BiquadState& state) {
  float y = b0 * x + state.v1;
  state.v1 = b1 * x - a1 * y + state.v2;
  state.v2 = b2 * x - a2 * y;
  return y;
}

void AFE44XX::apply_bandpass_filter(afe44xx_data *afe44xx_raw_data) {
  float ir_val = (float)afe44xx_raw_data->IRminusAmbient_data;
  float red_val = (float)afe44xx_raw_data->REDminusAmbient_data;

  ir_val = step_biquad(ir_val, BP_B0, BP_B1, BP_B2, BP_A1, BP_A2, ir_filter_state);
  red_val = step_biquad(red_val, BP_B0, BP_B1, BP_B2, BP_A1, BP_A2, red_filter_state);

  afe44xx_raw_data->IR_filtered_data = (signed long)ir_val;
  afe44xx_raw_data->RED_filtered_data = (signed long)red_val;
}