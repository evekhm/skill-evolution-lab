# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
from zoneinfo import ZoneInfo
from google.adk.plugins import LoggingPlugin
from google.adk.plugins.bigquery_agent_analytics_plugin import BigQueryLoggerConfig, BigQueryAgentAnalyticsPlugin

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types
import os
import google.auth

from dotenv import load_dotenv

# Load .env from project root if it exists
env_path = os.path.join(os.path.dirname(__file__), "../../../.env")
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)
_, project_id = google.auth.default()

# Big Query
DATASET_ID = os.getenv('DATASET_ID')
DATASET_LOCATION = os.getenv('DATASET_LOCATION')
TABLE_ID = os.getenv('TABLE_ID')
LOCATION = os.getenv('MODEL_LOCATION') or os.getenv('GOOGLE_CLOUD_LOCATION') or "global"  # model endpoint: gemini-3.x is global-only
MODEL_ID = os.getenv('HR_CALCULATOR_MODEL_ID', os.getenv('EVAL_MODEL_ID', "gemini-3.5-flash"))

os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
os.environ["GOOGLE_CLOUD_LOCATION"] = LOCATION
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

print(f"--- HR Calculator Environment Variables ---")
print(f"DATASET_ID: {DATASET_ID}")
print(f"DATASET_LOCATION: {DATASET_LOCATION}")
print(f"TABLE_ID: {TABLE_ID}")
print(f"GOOGLE_CLOUD_PROJECT: {os.environ.get('GOOGLE_CLOUD_PROJECT')}")
print(f"GOOGLE_CLOUD_LOCATION: {os.environ.get('GOOGLE_CLOUD_LOCATION')}")
print(f"-------------------------------------------")

def _get_us_holidays(year: int) -> list[datetime.date]:
    """Returns US public holidays for a given year."""
    holidays = {
        2025: [
            datetime.date(2025, 1, 1),   # New Year's Day
            datetime.date(2025, 1, 20),  # MLK Day
            datetime.date(2025, 2, 17),  # Presidents' Day
            datetime.date(2025, 5, 26),  # Memorial Day
            datetime.date(2025, 6, 19),  # Juneteenth
            datetime.date(2025, 7, 4),   # Independence Day
            datetime.date(2025, 9, 1),   # Labor Day
            datetime.date(2025, 10, 13), # Columbus Day
            datetime.date(2025, 11, 11), # Veterans Day
            datetime.date(2025, 11, 27), # Thanksgiving
            datetime.date(2025, 12, 25), # Christmas
        ],
        2026: [
            datetime.date(2026, 1, 1),   # New Year's Day
            datetime.date(2026, 1, 19),  # MLK Day
            datetime.date(2026, 2, 16),  # Presidents' Day
            datetime.date(2026, 5, 25),  # Memorial Day
            datetime.date(2026, 6, 19),  # Juneteenth
            datetime.date(2026, 7, 4),   # Independence Day (Saturday, observed July 3)
            datetime.date(2026, 9, 7),   # Labor Day
            datetime.date(2026, 10, 12), # Columbus Day
            datetime.date(2026, 11, 11), # Veterans Day
            datetime.date(2026, 11, 26), # Thanksgiving
            datetime.date(2026, 12, 25), # Christmas
        ],
    }
    return holidays.get(year, holidays[2026])


def _count_working_days(start: datetime.date, end: datetime.date) -> tuple[int, int, int]:
    """Count working days, weekends, and holidays between two dates (inclusive)."""
    holidays = _get_us_holidays(start.year)
    if end.year != start.year:
        holidays += _get_us_holidays(end.year)

    weekends = 0
    holiday_count = 0
    total_days = (end - start).days + 1
    current = start
    while current <= end:
        if current.weekday() in [5, 6]:
            weekends += 1
        elif current in holidays:
            holiday_count += 1
        current += datetime.timedelta(days=1)
    work_days = total_days - weekends - holiday_count
    return work_days, weekends, holiday_count


def calculate_pto_details() -> str:
    """Calculates remaining days in the year, work days, weekends, and US public holidays,
    and calculates remaining PTO and sick leave balances.

    Returns:
        A string with the calculated details including PTO balance, sick leave balance,
        and a summary of remaining work days.
    """
    today = datetime.date.today()
    year = today.year
    end_of_year = datetime.date(year, 12, 31)

    work_days, weekends, num_holidays = _count_working_days(today, end_of_year)

    # Company policy: 20 PTO days/year, accrued monthly (~1.67/month)
    # Sick leave: 10 days/year, accrued monthly (~0.83/month)
    months_elapsed = today.month - 1 + (today.day / 30.0)
    total_pto_accrued = round(months_elapsed * (20 / 12), 1)
    total_sick_accrued = round(months_elapsed * (10 / 12), 1)

    # Simulate some used days (assume ~30% used so far)
    pto_used = round(total_pto_accrued * 0.3, 1)
    sick_used = round(total_sick_accrued * 0.15, 1)

    remaining_pto = round(total_pto_accrued - pto_used, 1)
    remaining_sick = round(total_sick_accrued - sick_used, 1)

    # Future accrual for the rest of the year
    months_remaining = 12 - today.month + 1
    future_pto = round(months_remaining * (20 / 12), 1)
    future_sick = round(months_remaining * (10 / 12), 1)

    result = (
        f"As of today, {today.strftime('%Y-%m-%d')}:\n"
        f"- Total calendar days remaining in {year}: {(end_of_year - today).days + 1}\n"
        f"- Weekends remaining: {weekends}\n"
        f"- Public holidays remaining: {num_holidays}\n"
        f"- Work days remaining: {work_days}\n\n"
        f"Leave Balances:\n"
        f"- PTO accrued so far: {total_pto_accrued} days (used: {pto_used})\n"
        f"- Current PTO balance: {remaining_pto} days\n"
        f"- Sick leave accrued so far: {total_sick_accrued} days (used: {sick_used})\n"
        f"- Current sick leave balance: {remaining_sick} days\n"
        f"- Additional PTO to accrue this year: {future_pto} days\n"
        f"- Additional sick leave to accrue this year: {future_sick} days\n\n"
        f"Company Policy: 20 PTO days/year + 10 sick days/year, accrued monthly."
    )
    return result


def calculate_working_days_for_period(start_date: str, end_date: str) -> str:
    """Calculates working days, weekends, and holidays for a specific date range.
    Useful for planning vacations or understanding how many work days fall in a period.

    Args:
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.

    Returns:
        A string with the breakdown of working days, weekends, and holidays in the period.
    """
    try:
        start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return "Error: Please provide dates in YYYY-MM-DD format (e.g., 2026-07-15)."

    if end < start:
        return "Error: End date must be on or after start date."

    total_days = (end - start).days + 1
    work_days, weekends, holidays = _count_working_days(start, end)

    # Calculate PTO impact
    result = (
        f"Period: {start_date} to {end_date}\n"
        f"- Total calendar days: {total_days}\n"
        f"- Working days: {work_days}\n"
        f"- Weekend days: {weekends}\n"
        f"- Public holidays: {holidays}\n\n"
        f"If you take vacation for this entire period, you would use {work_days} PTO days.\n"
    )

    # Add month-specific info
    if start.month == end.month:
        month_start = datetime.date(start.year, start.month, 1)
        if start.month == 12:
            month_end = datetime.date(start.year, 12, 31)
        else:
            month_end = datetime.date(start.year, start.month + 1, 1) - datetime.timedelta(days=1)
        total_work_in_month, _, _ = _count_working_days(month_start, month_end)
        remaining_work = total_work_in_month - work_days
        result += f"- Total working days in {start.strftime('%B %Y')}: {total_work_in_month}\n"
        result += f"- Working days remaining after this vacation: {remaining_work}\n"

    return result


def get_remaining_working_days(period: str = "month") -> str:
    """Calculates remaining working days until the end of the current month, quarter, or year.

    Args:
        period: One of 'month', 'quarter', or 'year'. Defaults to 'month'.

    Returns:
        A string with the number of remaining working days for the specified period.
    """
    today = datetime.date.today()
    year = today.year

    if period == "month":
        if today.month == 12:
            end = datetime.date(year, 12, 31)
        else:
            end = datetime.date(year, today.month + 1, 1) - datetime.timedelta(days=1)
        period_name = today.strftime("%B %Y")
    elif period == "quarter":
        quarter = (today.month - 1) // 3 + 1
        quarter_end_month = quarter * 3
        if quarter_end_month == 12:
            end = datetime.date(year, 12, 31)
        else:
            end = datetime.date(year, quarter_end_month + 1, 1) - datetime.timedelta(days=1)
        period_name = f"Q{quarter} {year}"
    elif period == "year":
        end = datetime.date(year, 12, 31)
        period_name = str(year)
    else:
        return f"Error: Unknown period '{period}'. Use 'month', 'quarter', or 'year'."

    work_days, weekends, holidays = _count_working_days(today, end)

    result = (
        f"Remaining working days until end of {period_name}:\n"
        f"- Working days: {work_days}\n"
        f"- Weekend days: {weekends}\n"
        f"- Public holidays: {holidays}\n"
        f"- Calendar days: {(end - today).days + 1}\n"
        f"- Period ends: {end.strftime('%Y-%m-%d')}"
    )
    return result


# Short-term disability policy parameters (mirror the company policy corpus:
# 60% income replacement, 12-week maximum, 7-day unpaid waiting period).
_STD_INCOME_REPLACEMENT = 0.6
_STD_MAX_WEEKS = 12


def calculate_disability_pay(annual_salary: float, weeks_out: int) -> dict:
    """Compute short-term-disability (STD) pay for a given salary and leave length.

    This is a CALCULATION, not a lookup: STD replaces 60% of salary for up to 12
    weeks after a 7-day waiting period, so the dollar payout depends on the
    employee's salary and how many weeks they are out. The 7-day waiting period
    is unpaid time before benefits begin -- it does NOT reduce the number of
    payable weeks, so ``weeks_out`` counts benefit weeks and every covered week
    is paid. Use this whenever the user asks "how much would short-term
    disability pay me" with a specific salary and/or duration -- a policy
    lookup only returns the 60%/12-week policy, never the dollar amount.

    Args:
        annual_salary: The employee's gross annual salary in dollars.
        weeks_out: Number of benefit weeks the employee expects to be on
            disability. When the user says they are "out for N weeks",
            pass N directly -- NEVER subtract the 7-day waiting period
            from it (the waiting period never reduces payable weeks).

    Returns:
        A dict with the weekly and total STD benefit, the covered weeks (capped
        at the 12-week maximum), and the policy parameters used.
    """
    covered_weeks = min(weeks_out, _STD_MAX_WEEKS)
    weekly_benefit = (annual_salary / 52.0) * _STD_INCOME_REPLACEMENT
    return {
        "annual_salary": annual_salary,
        "weeks_requested": weeks_out,
        "covered_weeks": covered_weeks,
        "capped_at_max": weeks_out > _STD_MAX_WEEKS,
        "weekly_benefit": round(weekly_benefit, 2),
        "total_benefit": round(weekly_benefit * covered_weeks, 2),
        "income_replacement_rate": _STD_INCOME_REPLACEMENT,
        "max_weeks": _STD_MAX_WEEKS,
    }


root_agent = Agent(
    name="hr_calculator",
    model=Gemini(
        model=MODEL_ID,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    description="An agent that calculates PTO balances, sick leave balances, working days for date ranges, remaining work days in a period, and short-term disability payouts.",
    instruction=(
        "You are a friendly and helpful PTO & Leave assistant. You can help with:\n"
        "1. **PTO and sick leave balances** - Use calculate_pto_details to get current balances.\n"
        "2. **Vacation planning** - Use calculate_working_days_for_period with start_date and end_date "
        "to calculate how many PTO days a vacation would cost and how many working days remain.\n"
        "3. **Remaining working days** - Use get_remaining_working_days with period='month', 'quarter', or 'year' "
        "to find out how many working days are left.\n"
        "4. **Short-term disability payouts** - Use calculate_disability_pay with the user's "
        "annual_salary and weeks_out to compute the personalized dollar amount (60% of salary, "
        "up to 12 weeks, after a 7-day unpaid waiting period).\n\n"
        "IMPORTANT: Resolve relative dates yourself. You know today's date from calculate_pto_details output. "
        "When a user says 'next Tuesday', 'this Friday', 'next week', etc., compute the actual YYYY-MM-DD date "
        "and call the tool directly. Do NOT ask the user to provide dates in a specific format -- figure it out. "
        "For 'a week off starting next Tuesday', calculate start_date = next Tuesday, end_date = following Monday "
        "(or Friday if they mean a work week), then call calculate_working_days_for_period.\n\n"
        "Always use the appropriate tool to get data before answering. "
        "Present the information clearly and in a friendly tone. "
        "When users ask about sick leave, use calculate_pto_details which includes sick leave balances. "
        "When users ask about specific date ranges or vacation periods, use calculate_working_days_for_period. "
        "When users ask about remaining days in the month, quarter, or fiscal quarter, use get_remaining_working_days."
    ),
    tools=[
        calculate_pto_details,
        calculate_working_days_for_period,
        get_remaining_working_days,
        calculate_disability_pay,
    ],
)

_agent_version = os.getenv("AGENT_VERSION", "0")

bq_config = BigQueryLoggerConfig(
    enabled=True,
    max_content_length=500 * 1024,
    batch_size=1,
    shutdown_timeout=10.0,
    custom_tags={"agent_version": _agent_version},
)
bq_logging_plugin = BigQueryAgentAnalyticsPlugin(
    project_id=project_id,
    dataset_id=DATASET_ID,
    table_id=TABLE_ID,
    config=bq_config,
    location=DATASET_LOCATION,
)
app = App(
    root_agent=root_agent,
    name="hr_calculator",
    plugins=[bq_logging_plugin, LoggingPlugin()]
)
