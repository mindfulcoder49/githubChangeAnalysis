import subprocess
from datetime import datetime, timedelta
import re
import os
from dotenv import load_dotenv
from openai import OpenAI
from flask import Flask, jsonify, request
import functions_framework

# Load environment variables from .env file
load_dotenv()
client = OpenAI()



def clone_repository(local_path, remote_url):
    if not os.path.exists(local_path):
        os.makedirs(local_path, exist_ok=True)
        cmd = ['git', 'clone', remote_url, local_path]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

def find_commit_by_date(repo_path, date):
    cmd = ['git', '-C', repo_path, 'log', '--until', f"{date.isoformat()}", '-1', '--format=%H']
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    else:
        print(f"No commit found for {date}")
        return None

def generate_diff(repo_path, start_time, end_time):
    try:
        start_commit = find_commit_by_date(repo_path, start_time)
        end_commit = find_commit_by_date(repo_path, end_time)
        if not start_commit or not end_commit:
            return None
        cmd = ['git', '-C', repo_path, 'diff', '--stat', start_commit, end_commit]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            raise Exception(f"Git diff command failed with error: {result.stderr}")
        return result.stdout
    except Exception as e:
        print(f"Error generating diff: {e}")
        return None

# Function to process diffs over a time interval
def generate_diffs_over_time(repo_path, interval_hours, end_time, iterations=None, start_date=None):
    diffs = []
    current_end_time = end_time
    count = 0

    while True:
        start_time = current_end_time - timedelta(hours=interval_hours)
        diff = generate_diff(repo_path, start_time, current_end_time)
        if diff:
            diffs.append(diff)
        current_end_time = start_time
        count += 1

        # Break conditions
        if iterations and count >= iterations:
            break
        if start_date and start_time <= start_date:
            break

    return diffs

# Function to process and summarize diffs
def process_diff(diff_text):
    if not diff_text:
        return {}
    files_updated = re.findall(r'(\S+?)\s+\|\s+\d+\s+\+*\-*', diff_text)
    line_changes = re.findall(r'\|\s+(\d+)\s+\+*\-*', diff_text)
    summary = {file: int(lines) for file, lines in zip(files_updated, line_changes)}
    return summary


def summarize_changes(changes):
    # Get top 5 files with the most lines changed
    top_changes = sorted(changes.items(), key=lambda item: item[1], reverse=True)[:10]

    # Total lines changed
    total_lines_changed = sum(changes.values())

    # Number of files changed
    total_files_changed = len(changes)

    # Create a summary string
    summary = "Top 10 files with the most changes:\n"
    for file, lines in top_changes:
        summary += f"{file}: {lines} lines changed\n"

    summary += f"\nTotal lines changed: {total_lines_changed}\n"
    summary += f"Total files changed: {total_files_changed}"

    return summary

def generate_diffs_and_summaries(repo_name, repo_info, time_interval, iterations):
    print(f"Processing repository: {repo_name}")
    clone_repository(repo_info['local_path'], repo_info['remote_url'])
    end_time = datetime.now()
    repo_path = repo_info['local_path']
    diffs = generate_diffs_over_time(repo_path, time_interval, end_time, iterations)
    diff_summaries = []
    diffs_with_summary = []
    if diffs:
        for diff in diffs:
            if diff:
                summary = process_diff(diff)
                summarized_info = summarize_changes(summary)
                print(f"Diff for {repo_name}: {summarized_info} {summary}")
                diff_summaries.append(summarized_info)
                diffs_with_summary.append([diff,summarized_info])
            else:
                print(f"No changes detected for {repo_name} in this interval.")
    else:
        print(f"No diffs found for {repo_name}")
        return None

    return diffs_with_summary

def generate_diff_analysis(diff,diff_summary):
  prompt_intro = f"Here is information from a diff on an open source code repository. Provide an analysis on what types of changes occurred based on the diff information"

  report = prompt_intro + diff + diff_summary
  completion = client.chat.completions.create(
      model="gpt-3.5-turbo-0125",
      messages=[
          {"role": "user", "content": report}
      ]
  )

  response_content = completion.choices[0].message.content
  return response_content

def generate_all_diff_analyses(diffs):
  analyses = []
  for diff in diffs:
      analysis = generate_diff_analysis(diff[0],diff[1])
      analyses.append(analysis)
  return analyses

def print_analyses(analyses):
  #create a loop with a numerical index value holder
  for i, analysis in enumerate(analyses):
    print(f"Analysis {i+1}:\n {analysis}")

#run the functions to get analyses of opendevin and devika

@functions_framework.http
def main(request):

    # List of repositories with their local paths and remote URLs
    repos = {
        'opendevin': {
            'local_path': './opendevin',
            'remote_url': 'https://github.com/OpenDevin/OpenDevin.git'
        },
        'devika': {
            'local_path': './devika',
            'remote_url': 'https://github.com/stitionai/devika.git'
        }
    }

    #check if request is for a specific repo
    repo_name = request.args.get('repo')
    time_interval = request.args.get('interval', 120)
    time_interval = int(time_interval)
    iterations = request.args.get('iterations', 5)
    iterations = int(iterations)
    if repo_name:
        repo_info = repos.get(repo_name)
        if repo_info:

            diffs_with_summary = generate_diffs_and_summaries(repo_name, repo_info, time_interval, iterations)
            if diffs_with_summary:
                analyses = generate_all_diff_analyses(diffs_with_summary)
                return jsonify(analyses)
            else:
                return jsonify(f"No diffs found for {repo_name}")
        else:
            return jsonify(f"Repository {repo_name} not found")
    else:
        #do nothing
        return jsonify("No repository specified")
