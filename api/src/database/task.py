from io import StringIO

import requests

from src.database.client import table, bucket
from typing import *
import os
import re
from pandas import DataFrame
import pandas as pd

from src.database.util import insert_info_row


class Task:
    task_id: int
    task_name: str  # human-readable
    user_id: str  # just the email for now

    def __init__(self, user_id: str, task_id: int | None = None, task_name: str | None = None,
                 initial_df: DataFrame | None = None, initial_df_frontend: DataFrame | None = None):
        """ Create a new task for a new initial_df DataFrame or retrieve an existing task with task_id """
        self.user_id = user_id
        self.task_id = task_id
        self.task_name = task_name

        if self.task_id is None:
            # create a new task
            task_ids: List = table.select('task_id').execute().data
            max_id = max([id['task_id'] for id in task_ids]) if not task_ids == [] else 0
            self.task_id = max_id + 1

            if initial_df is None:
                raise ValueError('initial_df must be provided when creating a new task, i.e. when task_id is None')
            if initial_df_frontend is None:
                initial_df_frontend = self.df_to_frontend_df(initial_df)
            # Upload first step
            self.upload_step(step_id=str(self.task_id)+'_0', step_count=0, transformation='', explanation='Initial DataFrame', df_after=initial_df, df_frontend=initial_df_frontend)

    def max_step_count(self) -> int:
        step_counts: List = table.select('task_id, step_count').eq('task_id', self.task_id).execute().data
        if len(step_counts) <= 1:  # start max_step_count at 0 if there are no steps yet
            return 0
        max_step_count = max([int(c['step_count']) for c in step_counts])
        return max_step_count
    
    def retrieve_previous_steps(self) -> List[Dict]:
        """ Retrieve the previous steps for this task """
        return table.select('explanation').eq('task_id', self.task_id).execute().data

    def df_to_frontend_df(self, df: DataFrame, num_rows: int = 10) -> DataFrame:
        """ Convert a DataFrame to a shorter DataFrame that can be displayed in the frontend """
        frontend_df = insert_info_row(df)
        return frontend_df.head(num_rows + 1)

    def _get_df_at_url(self, url: str) -> DataFrame:
        """ Get the DataFrame at a given url """
        csv_string = requests.get(url).text
        df: DataFrame = pd.read_csv(StringIO(csv_string))
        return df

    def get_latest_data(self) -> Dict:
        data_dict = table.select('*').eq('task_id', self.task_id).eq('step_count', self.max_step_count()) \
            .execute().data[0]
        return data_dict

    def get_latest_df(self) -> DataFrame:
        """ Get the DataFrame corresponding to the latest step in the task """
        url = self.get_latest_data()['df_after']
        return self._get_df_at_url(url)

    def get_history(self) -> List[Dict]:
        """
        Get the history of transformations for this task. Sample output:
        [
        {'step_count': 5, 'transformation': 'def f(): ...', 'explanation': 'Robert transformation with a change', 'df_after': DataFrame}
        ]
        """
        history: List[Dict] = table.select('step_count, transformation, explanation, df_after').eq('task_id',
                                                                                                   self.task_id).execute().data
        for step in history:
            step['df_after'] = self._get_df_at_url(step['df_after'])
        return history

    def upload_step(self, step_id: str, step_count: int, transformation: str, explanation: str, df_after: DataFrame, df_frontend: DataFrame):
        """ Upload a step in the task to the DB """
        # convert dataframes to csv
        os.makedirs('temp', exist_ok=True)
        df_after.to_csv('temp/df.csv', index=False)
        with open('temp/df.csv', 'rb') as f:
            filepath = f'{self.user_id}/df_after_{step_id}.csv'
            bucket.upload(filepath, f)
            df_after_url = bucket.get_public_url(filepath)
        df_frontend.to_csv('temp/df.csv', index=False)
        with open('temp/df.csv', 'rb') as f:
            filepath = f'{self.user_id}/df_frontend_{step_id}.csv'
            bucket.upload(filepath, f)
            df_frontend_url = bucket.get_public_url(filepath)
        os.remove('temp/df.csv')

        table.insert({
            'step_id': step_id,
            'task_id': self.task_id,
            'task_name': self.task_name,
            'step_count': step_count,
            'user_id': self.user_id,
            'transformation': transformation,
            'explanation': explanation,
            'df_after': df_after_url,
            'df_frontend': df_frontend_url
        }).execute()

    def upload_new_step(self, transformation: str, explanation: str, df_after: DataFrame, df_frontend: DataFrame):
        """ Upload a new step in the task to the DB """
        step_count = self.max_step_count() + 1
        step_id = str(self.task_id) + '_' + str(step_count)
        self.upload_step(step_id, step_count, transformation, explanation, df_after, df_frontend)


if __name__ == '__main__':
    my_df = DataFrame({'a': [1, 2, 3]})
    # Create a new task for Alex
    # task = Task(user_id='alex@example.com', task_name="Alex's Task", initial_df=my_df, initial_df_frontend=my_df)
    # task.upload_new_step('lambda x: x', 'Alex transformation 1 - no change', my_df, my_df)

    # Create a new task for Robert
    task1 = Task(user_id='robert@example.com', task_name="Robert's Task", initial_df=my_df)
    task2 = Task(user_id='robert@example.com', task_id=task1.task_id)
    task3 = Task(user_id='robert@example.com', task_id=task1.task_id)
    print(task1.max_step_count(), ' ', task2.max_step_count())
    task1.upload_new_step('lambda x: x', 'Robert transformation 1 - no change', my_df, my_df)
    print(task1.max_step_count(), ' ', task2.max_step_count())
    task2.upload_new_step('lambda x: x', 'Robert transformation 2 - no change', my_df, my_df)
    print(task1.max_step_count(), ' ', task2.max_step_count())
    task3.upload_new_step('lambda x: x', 'Robert transformation 3 - no change', my_df, my_df)
    task3.upload_new_step('lambda x: x', 'Robert transformation 4 - no change', my_df, my_df)
    task3.upload_new_step('lambda x: x', 'Robert transformation 5 - no change', my_df, my_df)
    print(task1.max_step_count(), ' ', task2.max_step_count())
    task1.upload_new_step('def f(): ...', 'Robert transformation with a change', DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]}), my_df)
    print(task1.max_step_count(), ' ', task2.max_step_count())

    # Retrieve Robert's task with task_id 12
    # task = Task(user_id='robert@example.com', task_id=12)
    # h = task.get_history()
    # print(h)

    # task = Task(user_id='robert@example.com', task_id=34)
    # m = task.max_step_count()
    # print(m)
