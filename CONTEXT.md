### Objective
The main objective of the project is to develop a **justified** salary model for DevOps/SRE (potentially even MLOps, DevSecOps...) specialists. The project aims to move away from the company's current linear salary model. 

### Data Collection
There are 3 main sources of vacancies: hh.ru, career.habr and telegram. Each source has its own respective crawler (crawls the pages for the search queries and retrieves links) and parser (checks the links and extracts respective info). They are all ran by using the orchestrator - main.py.  
### Data Storage 
Throughout the project data will be stored in the local database 'hilbert' which runs on PostgreSQL. The main table is 'vacancies' with following key columns:
- title: text
- job_description: text
- salary_from: int
- salary_to: int
- remote: bool
- location: text

### Data Preprocessing
For vacancies that are retrieved from hh.ru and career.habr job descriptions are filtered from html-artefacts by using the script: description_cleaner.py. 

Non-relevant entries (e.g not DevOps...) are removed by running an SQL query (filter.sql). 

# TODO: 
### Skill extraction
The skill extraction will be later performed by first extracting skills for some batch of descriptions via LLM and then fine-tuning some BERT-like model. 

### Econometric modeling
Since the main goal of the project is to build a justified salary model, the focus should be on unbiasedness of the estimates in the Mincer-type wage model. That is why econometric approach is chosen. However, we might also build decision trees. 

Seniority grades are going to be used in the model on par with extracted skills (interaction terms), so the missing data for seniority grades will be modeled by using an ordered logit (we should thoroughly think through this stage)  