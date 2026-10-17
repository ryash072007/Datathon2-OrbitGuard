# Prerequisite labs on IBM LinuxONE

Both notebooks from [linuxone-community-cloud/jupyter-lab-ml](https://github.com/linuxone-community-cloud/jupyter-lab-ml) were run end to end on the team's LinuxONE VM (s390x, machine type 9175, 3 CPUs) on 2026-10-17, inside IBM's Jupyter Lab container.

| Lab | Notebook | What it does | Result on LinuxONE |
|---|---|---|---|
| 1 | [Churn_Scikit_PyTorch_executed_on_LinuxONE.ipynb](Churn_Scikit_PyTorch_executed_on_LinuxONE.ipynb) | Joins 20,000 transactions with 6,001 clients in pandas, explores churn with 7 plots, trains a scikit-learn Random Forest and exports it to PMML, then trains a PyTorch classifier | 31 of 31 code cells ran, 0 errors, 18 s. PyTorch test accuracy 76.2% after 300 epochs |
| 2 | [Loan_Approval_Demo_executed_on_LinuxONE.ipynb](Loan_Approval_Demo_executed_on_LinuxONE.ipynb) | Hybrid AI loan decision: an IBM Granite LLM (llama.cpp built with zDNN/NNPA and OpenBLAS) extracts features from PDFs, an XGBoost model scores risk, BM25 retrieves lending policy, and the LLM writes a recommendation | 9 of 9 code cells ran, 0 errors, 65 s. Applicant 5: Low Risk (p = 0.997), recommendation "Approve" |
| - | [LinuxONE_environment_check.ipynb](LinuxONE_environment_check.ipynb) | Prints the platform from inside the same container | `s390x`, `IBM/S390`, machine 9175; scikit-learn 1.9.0, XGBoost 3.4.1, PyTorch 2.11.0 |

## Screenshots

Jupyter Lab, opened through an SSH tunnel to the VM:

- [0_environment_check.png](screenshots/0_environment_check.png): s390x / IBM/S390 / machine 9175
- [1_churn_top.png](screenshots/1_churn_top.png), [1_churn_correlations.png](screenshots/1_churn_correlations.png), [1_churn_pytorch_training.png](screenshots/1_churn_pytorch_training.png)
- [2_loan_zdnn.png](screenshots/2_loan_zdnn.png): llama.cpp zDNN/NNPA build and the Granite model
- [2_loan_risk_and_recommendation.png](screenshots/2_loan_risk_and_recommendation.png): LLM feature extraction and XGBoost risk score

## Environment

- Image: `registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest`, digest `sha256:d2da8a7b0c88c3b468e29014b2ada9ef8274f98c976ec456904c5e2bae5aa54c`
- Docker from Ubuntu's `docker.io` package (29.1.3)
- The container is bound to the VM's localhost (`-p 127.0.0.1:38888:38888`) and uses a random token. Port 38888 is not opened to the internet, unlike the lab's default setup. To open it from a laptop:

```
ssh -i key.pem -N -L 38888:127.0.0.1:38888 linux1@<VM_IP>
# token: ssh -i key.pem linux1@<VM_IP> 'cat ~/.jupyter-token'
# then open http://localhost:38888/lab?token=<token>
```

Re-run headless on the VM:

```
sudo docker exec -w /home/ibm-user notebook jupyter nbconvert --to notebook --execute \
  --output-dir shared/labs --output Loan_Approval_Demo_executed_on_LinuxONE Loan_Approval_Demo.ipynb
```

Note: the guidebook names two prerequisite labs; our reading is that they are the churn notebook (Lab 1) and the loan-approval notebook (Lab 2). The other two notebooks in the repo (fraud LSTM, MNIST) are also in the container if the organisers meant those.
