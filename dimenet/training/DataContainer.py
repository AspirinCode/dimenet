import numpy as np
import scipy.sparse as sp


feature_keys = ['id', 'Z', 'R', 'N']
target_keys = ['mu', 'alpha', 'homo', 'lumo',
               'gap', 'r2', 'zpve', 'U0', 'U', 'H', 'G', 'Cv']
index_keys = ["batch_seg", "idnb_i", "idnb_j", "id_expand_kj",
              "id_reduce_ji", "id3dnb_i", "id3dnb_j", "id3dnb_k"]


class DataContainer:
    def __init__(self, filename, cutoff):
        data_dict = np.load(filename)
        self._cutoff = cutoff
        for key in feature_keys + target_keys:
            if key in data_dict:
                setattr(self, "_" + key, data_dict[key])
            else:
                setattr(self, "_" + key, None)

        assert self._R is not None

    def _bmat_fast(self, mats):
        new_data = np.concatenate([mat.data for mat in mats])

        ind_offset = np.zeros(1 + len(mats))
        ind_offset[1:] = np.cumsum([mat.shape[0] for mat in mats])
        new_indices = np.concatenate(
            [mats[i].indices + ind_offset[i] for i in range(len(mats))])

        indptr_offset = np.zeros(1 + len(mats))
        indptr_offset[1:] = np.cumsum([mat.nnz for mat in mats])
        new_indptr = np.concatenate(
            [mats[i].indptr[i >= 1:] + indptr_offset[i] for i in range(len(mats))])
        return sp.csr_matrix((new_data, new_indices, new_indptr))

    def __len__(self):
        return self._R.shape[0]

    def __getitem__(self, idx):
        if type(idx) is int or type(idx) is np.int64:
            idx = [idx]

        data = {}
        for key in target_keys:
            if getattr(self, "_" + key) is not None:
                data[key] = getattr(self, "_" + key)[idx]
            else:
                data[key] = np.full(len(idx), np.nan, dtype=np.float32)
        if self._N is None:
            data['N'] = np.zeros(len(idx), dtype=np.int32)
        else:
            data['N'] = self._N[idx]
        data['batch_seg'] = np.repeat(np.arange(len(idx), dtype=np.int32), data['N'])
        adj_matrices = []

        data['Z'] = np.zeros(np.sum(data['N']), dtype=np.int32)
        data['R'] = np.zeros([np.sum(data['N']), 3], dtype=np.float32)

        nend = 0
        for k, i in enumerate(idx):
            n = data['N'][k]  # number of atoms
            nstart = nend
            nend = nstart + n

            if self._Z is not None:
                data['Z'][nstart:nend] = self._Z[i, :n]

            R = self._R[i, :n]
            data['R'][nstart:nend] = R

            Dij = np.linalg.norm(R[:, None, :] - R[None, :, :], axis=-1)
            adj_matrices.append(sp.csr_matrix(Dij <= self._cutoff))
            adj_matrices[-1] -= sp.eye(n, dtype=np.bool)

        # Entry x,y is edge x<-y (!)
        adj_matrix = self._bmat_fast(adj_matrices)
        # Entry x,y is edgeid x<-y (!)
        atomids_to_edgeid = sp.csr_matrix(
            (np.arange(adj_matrix.nnz), adj_matrix.indices, adj_matrix.indptr),
            shape=adj_matrix.shape)
        edgeid_to_target, edgeid_to_source = adj_matrix.nonzero()

        # Target (i) and source (j) nodes of edges
        data['idnb_i'] = edgeid_to_target
        data['idnb_j'] = edgeid_to_source

        # Indices of triplets k->j->i
        ntriplets = adj_matrix[edgeid_to_source].sum(1).A1
        id3ynb_i = np.repeat(edgeid_to_target, ntriplets)
        id3ynb_j = np.repeat(edgeid_to_source, ntriplets)
        id3ynb_k = adj_matrix[edgeid_to_source].nonzero()[1]

        # Indices of triplets that are not i->j->i
        id3_y_to_d, = (id3ynb_i != id3ynb_k).nonzero()
        data['id3dnb_i'] = id3ynb_i[id3_y_to_d]
        data['id3dnb_j'] = id3ynb_j[id3_y_to_d]
        data['id3dnb_k'] = id3ynb_k[id3_y_to_d]

        # Edge indices for interactions
        # j->i => k->j
        data['id_expand_kj'] = atomids_to_edgeid[edgeid_to_source, :].data[id3_y_to_d]
        # j->i => k->j => j->i
        data['id_reduce_ji'] = atomids_to_edgeid[edgeid_to_source, :].tocoo().row[id3_y_to_d]
        return data
