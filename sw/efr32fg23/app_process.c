/***************************************************************************//**
 * @file
 * @brief app_process.c
 *******************************************************************************
 * # License
 * <b>Copyright 2018 Silicon Laboratories Inc. www.silabs.com</b>
 *******************************************************************************
 *
 * SPDX-License-Identifier: Zlib
 *
 * The licensor of this software is Silicon Laboratories Inc.
 *
 * This software is provided 'as-is', without any express or implied
 * warranty. In no event will the authors be held liable for any damages
 * arising from the use of this software.
 *
 * Permission is granted to anyone to use this software for any purpose,
 * including commercial applications, and to alter it and redistribute it
 * freely, subject to the following restrictions:
 *
 * 1. The origin of this software must not be misrepresented; you must not
 *    claim that you wrote the original software. If you use this software
 *    in a product, an acknowledgment in the product documentation would be
 *    appreciated but is not required.
 * 2. Altered source versions must be plainly marked as such, and must not be
 *    misrepresented as being the original software.
 * 3. This notice may not be removed or altered from any source distribution.
 *
 ******************************************************************************/

// -----------------------------------------------------------------------------
//                                   Includes
// -----------------------------------------------------------------------------
#include "sl_status.h"
#include "sl_common.h"
#include "sl_core.h"
#include "sl_atomic.h"
#include "sl_component_catalog.h"
#include "sl_rail.h"
#include "sl_rail_util_init.h"
#include "sl_code_classification.h"

#include "app_assert.h"
#include "app_button_press.h"
#include "hcs300.h"

#if defined(SL_CATALOG_KERNEL_PRESENT)
#include "app_task_init.h"
#endif

// -----------------------------------------------------------------------------
//                              Macros and Typedefs
// -----------------------------------------------------------------------------

// -----------------------------------------------------------------------------
//                          Static Function Declarations
// -----------------------------------------------------------------------------

static void proceed(void);

static void step(void);

// -----------------------------------------------------------------------------
//                                Global Variables
// -----------------------------------------------------------------------------

// -----------------------------------------------------------------------------
//                                Static Variables
// -----------------------------------------------------------------------------
static volatile uint32_t proceed_requested = 0;

// -----------------------------------------------------------------------------
//                          Public Function Definitions
// -----------------------------------------------------------------------------
/******************************************************************************
 * Application state machine, called infinitely
 *****************************************************************************/
void app_process_action(void)
{
  ///////////////////////////////////////////////////////////////////////////
  // Put your application code here!                                       //
  // This is called infinitely.                                            //
  // Do not call blocking functions from here!                             //
  ///////////////////////////////////////////////////////////////////////////
  step();
}

/******************************************************************************
 * RAIL callback, called if a RAIL event occurs
 *****************************************************************************/
SL_CODE_RAM void sl_rail_util_on_event(sl_rail_handle_t rail_handle, sl_rail_events_t events)
{
  (void) rail_handle;
  (void) events;

  ///////////////////////////////////////////////////////////////////////////
  // Put your RAIL event handling here!                                    //
  // This is called from ISR context.                                      //
  // Do not call blocking functions from here!                             //
  ///////////////////////////////////////////////////////////////////////////

#if defined(SL_CATALOG_KERNEL_PRESENT)
  app_task_notify();
#endif
}

bool app_is_ok_to_sleep(void)
{
  return proceed_requested == 0;
}

void hcs300_proceed_cb(void)
{
  proceed();
}


// -----------------------------------------------------------------------------
//                          Static Function Definitions
// -----------------------------------------------------------------------------

static void proceed(void)
{
  sl_atomic_store(proceed_requested, 1);
}

static void step(void)
{
  volatile bool run_step = false;
  CORE_DECLARE_IRQ_STATE;
  CORE_ENTER_CRITICAL();
  if (proceed_requested) {
    proceed_requested = 0;
    run_step = true;
  }
  CORE_EXIT_CRITICAL();
  if (run_step) {
    hcs300_step();
  }
}

void hcs300_on_rx_packet(uint16_t hcs300_id,
                         bool rpt,
                         bool vlow,
                         uint8_t btn_status,
                         uint32_t serial,
                         uint32_t encrypted)
{
  uint8_t codeword_data[HCS300_CODEWORD_DATA_BYTES];
  uint16_t codeword_data_len = sizeof(codeword_data);

  sl_status_t sc = hcs300_create_codeword_data(hcs300_id,
                                               codeword_data,
                                               &codeword_data_len,
                                               rpt,
                                               vlow,
                                               btn_status,
                                               serial,
                                               encrypted);
  app_assert_status(sc);

  sl_rail_handle_t rail_handle = sl_rail_util_get_handle(SL_RAIL_UTIL_HANDLE_INST0);
  volatile int32_t tx_power_dbm = sl_rail_get_tx_power_dbm(rail_handle);
  sc = sl_rail_set_tx_power_dbm(rail_handle, 100);
  app_assert_status(sc);
  uint16_t tx_len = sl_rail_write_tx_fifo(rail_handle, codeword_data, sizeof(codeword_data), true);
  app_assert_s(tx_len == sizeof(codeword_data));
  sc = sl_rail_start_tx(rail_handle, 0, SL_RAIL_TX_OPTIONS_DEFAULT, NULL);
  app_assert_status(sc);
  sl_rail_delay_us(rail_handle, 100000);
}

void app_button_press_cb(uint8_t button, uint8_t duration)
{
  (void) duration;

  if (button == 0) {
    sl_status_t sc = hcs300_activate(HCS300_S0, false);
    app_assert_status(sc);
  } else if (button == 1)
  {
    sl_status_t sc = hcs300_activate(HCS300_S0, true);
    app_assert_status(sc);
  }

}
