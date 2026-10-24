import pyarrow
import pyarrow.parquet
from bridge_coupler import SimplifiedSimBridge
from prescribed_bridge_coupler import PrescribedSimBridge
from simulation import Simulation

class Logger:
    """Streams the macro field and mask state to gzip-compressed Parquet as the simulation runs.

    Rows are buffered and appended as Parquet row groups rather than held for the whole run.
    The previous accumulate-everything-then-write design needed ~6 GB per process at
    dx=8/dt=0.0625 (~24M rows) and made anything finer impossible; it also lost the
    entire log if a run was killed. Peak memory is now bounded by `flush_rows`
    regardless of run length or cell count.

    Values and row order are identical to the CSV logs this replaces -- every quantity is
    stored as float64, so nothing is rounded on the way out. Only the container changed.
    Columns like `time`, `dt` and `length` repeat for every cell of every step, which is
    what made the CSVs so large; dictionary-encoded and compressed they cost almost nothing.

    One behavioural difference from CSV: a Parquet file is only readable once its footer is
    written, and that happens in flush()/destroy(). Row groups still reach the disk
    incrementally, so memory stays bounded, but a run that dies before destroy() (SIGKILL,
    or an exception thrown past the call site) leaves a file that cannot be opened at all
    rather than a short valid one. Call sites that care should run destroy() from a finally.
    """

    # Buffered macro rows before a chunk is appended. Bounds memory independently of
    # how many active cells the mesh has.
    flush_rows = 250_000
    # Rows per Parquet row group. A flush of `flush_rows` is split into several groups so
    # readers can skip and stream in reasonable units; it does not affect peak memory here.
    row_group_rows = 50_000
    # Parquet codec. "zstd" (what simulation_dataset.py writes) is both smaller and
    # markedly faster to write than gzip, if portability of the output is not a concern.
    compression = "gzip"
    # Extension every log this class writes carries. Callers that build log paths should
    # read it from here rather than hardcoding one, so the format lives in one place.
    # analysis_helpers.LOG_SUFFIX duplicates the value on purpose: that module has to stay
    # importable in a notebook without dragging in the whole simulation stack.
    FILE_SUFFIX = ".parquet"

    MACRO_COLUMNS = (
        "time", "dt", "x_start_position", "length", "density", "velocity", "flow",
    )
    MASK_COLUMNS = (
        "time", "dt", "x_start_position", "length",
        "rear_density", "rear_velocity", "rear_flow",
        "front_density", "front_velocity", "front_flow",
        # Cumulative integral of the actual coupling flux, sum(net_flux * dt). Distinct from
        # rear_flow/front_flow above, which are just q(rho_interior) and ignore the exterior
        # state and the anchor speed. *_flux_memory is a running BALANCE that spawn/despawn
        # also debit and credit; *_flux_total is the pure integral. Reconcile against the
        # totals, never the memories.
        "rear_flux_memory", "front_flux_memory",
        "rear_flux_total", "front_flux_total",
        "vehicle_count",
    )
    # Per-vehicle trajectories. OFF unless vehicle_path is given, because the sweep does
    # not need them and the format of the two logs above must not change underneath the
    # analysis code. `s` is the ABSOLUTE road coordinate: bridge.vehicles holds absolute
    # positions, and collate_vehicles() is what converts to mask-relative for the fluid
    # side, so this reads the bridge rather than masking_cell.vehicles.
    VEHICLE_COLUMNS = (
        "time", "dt", "vehicle_id", "s", "s_dt", "length", "mask_rear_s",
    )

    # Arrow type per column. Everything logged is a float64 except the vehicle id, which is
    # the bridge's own string key. Types are declared rather than inferred per chunk because
    # ParquetWriter rejects a row group whose schema differs from the file's, and inference
    # on a buffer that happens to be empty yields a null column instead of a float one.
    COLUMN_TYPES = {"vehicle_id": pyarrow.string()}

    @classmethod
    def _schema(cls, columns):
        return pyarrow.schema(
            [(c, cls.COLUMN_TYPES.get(c, pyarrow.float64())) for c in columns])

    def __init__(self, sim: Simulation, bridge: SimplifiedSimBridge | PrescribedSimBridge = None, sim_macro_path="sim_data.parquet", mask_path="mask_data.parquet", callback_name="logger", vehicle_path=None, fd=None):
        # bridge=None is the mask-free control: the pure fluid solver, no micro domain.
        # No mask log is opened at all in that case -- a mask file full of zeros would read
        # as data to anything downstream. `fd` supplies the velocity relation that would
        # otherwise come off the bridge.
        self.sim_macro_data = {c: [] for c in self.MACRO_COLUMNS}
        self.mask_data = {c: [] for c in self.MASK_COLUMNS}
        self.vehicle_data = {c: [] for c in self.VEHICLE_COLUMNS}
        self.sim = sim
        self.bridge = bridge
        self.sim_macro_path = sim_macro_path
        self.mask_path = mask_path
        self.vehicle_path = vehicle_path
        self.callback_name = callback_name

        self._fd = fd if fd is not None else (bridge.fd if bridge is not None else None)
        if self._fd is None:
            raise ValueError("Logger needs either a bridge or an explicit fd")

        # Opened for the life of the run; truncates any previous output up front so a
        # killed run leaves an unfinished file rather than a stale complete one.
        self._macro_schema = self._schema(self.MACRO_COLUMNS)
        self._mask_schema = self._schema(self.MASK_COLUMNS)
        self._vehicle_schema = self._schema(self.VEHICLE_COLUMNS)
        self._macro_writer = self._open(sim_macro_path, self._macro_schema)
        self._mask_writer = self._open(mask_path, self._mask_schema) if bridge is not None else None
        self._vehicle_writer = self._open(vehicle_path, self._vehicle_schema) if vehicle_path else None
        self._closed = False

        sim.register_poststep_callback(self._step, callback_name)

    def _open(self, path, schema):
        return pyarrow.parquet.ParquetWriter(path, schema, compression=self.compression)

    def _step(self, sim_time: float, dt: float):
        for cell_id in self.sim.active.active_cells:
            cell = self.sim.active.active_cells[cell_id]
            cell_length = cell.length
            cell_x_start_position = cell.start_s
            cell_density = cell.mass / cell_length
            cell_velocity = self._fd.velocity_from_density(cell_density)
            cell_flow = cell_density * cell_velocity
            self.sim_macro_data["time"].append(sim_time)
            self.sim_macro_data["dt"].append(dt)
            self.sim_macro_data["x_start_position"].append(cell_x_start_position)
            self.sim_macro_data["length"].append(cell_length)
            self.sim_macro_data["density"].append(cell_density)
            self.sim_macro_data["velocity"].append(cell_velocity)
            self.sim_macro_data["flow"].append(cell_flow)

        if self.bridge is None:
            # Mask-free control: nothing below this point exists.
            if len(self.sim_macro_data["time"]) >= self.flush_rows:
                self._write_chunk()
            return

        self.mask_data["time"].append(sim_time)
        self.mask_data["dt"].append(dt)
        # Read the mask window off the active mesh rather than off bridge.middle_s.
        # move_active_masks() shifts the mesh mask by anchor_speed*dt during the step,
        # and SimplifiedSimBridge only refreshes middle_s on the *next* _step, so the
        # bridge value lags the mesh by one anchor step. Downstream analysis uses this
        # position to exclude the mask cell, so it has to be the mesh's own geometry.
        mask_cell = self.sim.active.get_cell_with_mask(self.bridge._mask_id(self.bridge.lane_id))
        if mask_cell is not None:
            mask_rear_s = float(mask_cell.start_s)
            mask_length = float(mask_cell.end_s - mask_cell.start_s)
        else:
            # Bridge already destroyed: no mask cell to exclude, fall back to its last geometry.
            mask_rear_s = self.bridge.middle_s - self.bridge.margin_s
            mask_length = self.bridge.margin_s * 2.0
        self.mask_data["x_start_position"].append(mask_rear_s)
        self.mask_data["length"].append(mask_length)
        rear_density = self.bridge.masking_cell.get_rear_density(self.bridge.fd)
        rear_velocity = self.bridge.fd.velocity_from_density(rear_density)
        rear_flow = rear_density * rear_velocity
        front_density = self.bridge.masking_cell.get_front_density(self.bridge.fd)
        front_velocity = self.bridge.fd.velocity_from_density(front_density)
        front_flow = front_density * front_velocity
        self.mask_data["rear_density"].append(rear_density)
        self.mask_data["rear_velocity"].append(rear_velocity)
        self.mask_data["rear_flow"].append(rear_flow)
        self.mask_data["front_density"].append(front_density)
        self.mask_data["front_velocity"].append(front_velocity)
        self.mask_data["front_flow"].append(front_flow)
        self.mask_data["rear_flux_memory"].append(self.bridge.masking_cell.rear_flux_memory)
        self.mask_data["front_flux_memory"].append(self.bridge.masking_cell.front_flux_memory)
        self.mask_data["rear_flux_total"].append(self.bridge.masking_cell.rear_flux_total)
        self.mask_data["front_flux_total"].append(self.bridge.masking_cell.front_flux_total)
        self.mask_data["vehicle_count"].append(len(self.bridge.masking_cell.vehicles))

        if self._vehicle_writer is not None:
            # getattr: PrescribedSimBridge and a torn-down bridge may not carry a vehicle
            # dict, and a missing trajectory log must never abort a run.
            for vehicle_id, vehicle in getattr(self.bridge, "vehicles", {}).items():
                self.vehicle_data["time"].append(sim_time)
                self.vehicle_data["dt"].append(dt)
                self.vehicle_data["vehicle_id"].append(vehicle_id)
                self.vehicle_data["s"].append(vehicle.s)
                self.vehicle_data["s_dt"].append(vehicle.s_dt)
                self.vehicle_data["length"].append(vehicle.length)
                self.vehicle_data["mask_rear_s"].append(mask_rear_s)

        if len(self.sim_macro_data["time"]) >= self.flush_rows:
            self._write_chunk()

    def _append(self, writer, schema, buffer, columns):
        """Write one buffer out as Parquet row groups, or nothing if it is empty."""
        if (writer is None) or (not buffer[columns[0]]):
            return
        table = pyarrow.Table.from_pydict({c: buffer[c] for c in columns}, schema=schema)
        writer.write_table(table, row_group_size=self.row_group_rows)

    def _write_chunk(self):
        """Append the buffered rows to disk and clear the buffers.

        Each file's schema is fixed when it is opened, so unlike the CSV version there is
        no header to coordinate: a step where one buffer happens to be empty simply
        contributes no row group to that file.
        """
        if self._closed:
            return
        self._append(self._macro_writer, self._macro_schema, self.sim_macro_data, self.MACRO_COLUMNS)
        self._append(self._mask_writer, self._mask_schema, self.mask_data, self.MASK_COLUMNS)
        self._append(self._vehicle_writer, self._vehicle_schema, self.vehicle_data, self.VEHICLE_COLUMNS)
        for buf in (self.sim_macro_data, self.mask_data, self.vehicle_data):
            for column in buf:
                buf[column].clear()

    def flush(self):
        """Write any remaining buffered rows and close the files.

        Closing is what writes each Parquet footer, so this is not optional: until it runs
        the files on disk have no readable metadata.
        """
        if self._closed:
            return
        self._write_chunk()
        self._macro_writer.close()
        if self._mask_writer is not None:
            self._mask_writer.close()
        if self._vehicle_writer is not None:
            self._vehicle_writer.close()
        self._closed = True

    def destroy(self):
        self.flush()
        self.sim.unregister_poststep_callback(self.callback_name)
