import numpy as np
from itertools import product
from copy import copy
from tools import SIMULATORS, MAX_JOBS_PER_ONE, BACKENDS, chunks


from qiskit import execute, QuantumCircuit
from qiskit.tools.monitor import job_monitor
from qiskit.tools.qcvv.tomography import fit_tomography_data, tomography_set
from qiskit.tools.qcvv.tomography import tomography_data, create_tomography_circuits


def sort_list_and_transformation_matrix(a):
    """
    This is to sorts qubit. Also, it returns S matrix for changed density matrix
    :param a: list
    :return: (list, np.array(2**len(a), 2**len(a)))
    """
    length = len(a)
    S = np.eye(2**length, 2**length)
    b = copy(a)
    # bubble sort
    for i in range(length):
        for j in range(length-i-1):
            if b[j] > b[j+1]:
                b[j], b[j+1] = b[j+1], b[j]

                step_matrix = np.eye(2**length, 2**length)
                for digits in product([0, 1], repeat=length):
                    if digits[j] == digits[j+1]:
                        continue

                    first_number = sum([bit*2**n for n, bit in enumerate(digits)])
                    second_number = 0
                    for n, bit in enumerate(digits):
                        if n == j:
                            second_number += bit*2**(j+1)
                        elif n == j + 1:
                            second_number += bit*2**j
                        else:
                            second_number += bit*2**n

                    step_matrix[first_number, second_number] = 1
                    step_matrix[second_number, first_number] = 1
                    step_matrix[first_number, first_number] = 0
                    step_matrix[second_number, second_number] = 0

                S = step_matrix@S
    return b, S


class Launcher:
    def __init__(self, backend_name='ibmq_16_melbourne', shots=8192):
        self.shots = shots

        self.backend = next(filter(lambda x: x.name() == backend_name, BACKENDS))

        if backend_name in SIMULATORS:
            self.max_jobs_per_one = 10**6  # approximately infinity :)
        else:
            self.max_jobs_per_one = MAX_JOBS_PER_ONE

    def run(self, circuits, meas_qubits=None, measure=None, count_chunks=False):
        """
        :param circuits: list of QuantumCircuit or QuantumCircuit
        :param meas_qubits: list of qubits that will be measured.
        :param measure: optional. By default after channel transformation we do tomography.
        Not implemented now
        :return: depend on measure parameter. By default, it's list of density matrix
        """
        if measure is not None:
            raise NotImplementedError

        if isinstance(circuits, QuantumCircuit):
            circuits = [circuits]

        meas_qubits, s_matrix = sort_list_and_transformation_matrix(meas_qubits)

        tomo_set = tomography_set(meas_qubits)
        number_measure_experiments = 3**len(meas_qubits)

        jobs = []
        for qc in circuits:
            q, c = qc.qregs[0], qc.cregs[0]
            tomo_circuits = create_tomography_circuits(qc, q, c, tomo_set)
            jobs.extend(tomo_circuits)

        res = None
        for i, chunk_jobs in enumerate(chunks(jobs, self.max_jobs_per_one)):
            if count_chunks:
                print(f'chunk number: {i + 1}')
            execute_kwargs = {
                'circuits': chunk_jobs,
                'backend': self.backend,
                'shots': self.shots,
                'max_credits': 15
            }

            job_exp = execute(**execute_kwargs)
            job_monitor(job_exp)
            new_res = job_exp.result()

            if res is None:
                res = new_res
            else:
                res += new_res

        matrices = []
        for i in range(int(len(res.results) / number_measure_experiments)):
            res_matrix = copy(res)
            res_matrix.results = res.results[
                i*number_measure_experiments:(i + 1)*number_measure_experiments
            ]
            tomo_data = tomography_data(
                res_matrix, circuits[i].name, tomo_set
            )
            rho = np.linalg.inv(s_matrix)@fit_tomography_data(tomo_data)@s_matrix
            matrices.append(rho)
        return matrices
